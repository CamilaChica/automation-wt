import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from fastapi import Depends, HTTPException, Request, status
from psycopg2 import connect as postgres_connect
from psycopg2.extras import RealDictCursor

AUTH_DB_PATH = os.getenv("WT_AUTH_DB", "data/winged_tycoons_auth.db")
INTERNAL_DOMAIN = "wingedtycoons.com"
OTP_TTL_SECONDS = 5 * 60
SESSION_TTL_SECONDS = 8 * 60 * 60
MAX_OTP_REQUESTS_PER_HOUR = 3
MAX_OTP_ATTEMPTS = 5
OTP_LOCK_SECONDS = 15 * 60
AUTH_ENV = os.getenv("WT_AUTH_ENV", os.getenv("WT_ENV", "development")).strip().lower()
RUNTIME_ENV = os.getenv("WT_ENV", AUTH_ENV).strip().lower()
if RUNTIME_ENV == "production" and AUTH_ENV != "production":
    raise RuntimeError("WT_AUTH_ENV must be production when WT_ENV is production.")
IS_PRODUCTION = RUNTIME_ENV == "production" or AUTH_ENV == "production"
AUTH_STORAGE_BACKEND = os.getenv(
    "WT_AUTH_STORAGE_BACKEND",
    "postgres" if IS_PRODUCTION else "sqlite",
).strip().lower()
if AUTH_STORAGE_BACKEND not in {"sqlite", "postgres"}:
    raise RuntimeError("WT_AUTH_STORAGE_BACKEND must be 'sqlite' or 'postgres'.")
if IS_PRODUCTION and AUTH_STORAGE_BACKEND != "postgres":
    raise RuntimeError("Production authentication requires WT_AUTH_STORAGE_BACKEND=postgres.")
AUTH_SECRET = os.getenv("WT_AUTH_SECRET", "").strip()
if IS_PRODUCTION and len(AUTH_SECRET) < 32:
    raise RuntimeError("WT_AUTH_SECRET must be at least 32 characters in production.")
if not AUTH_SECRET:
    AUTH_SECRET = "development-only-change-this-secret"
ROLE_CUSTOMER = "ROLE_CUSTOMER"
ROLE_INTERNAL = "ROLE_INTERNAL"
STAFF_DEFAULT_ROLE = os.getenv("WT_STAFF_DEFAULT_ROLE", "ROLE_MANAGER").strip().upper()
OWNER_ADMIN_EMAIL = os.getenv("WT_OWNER_ADMIN_EMAIL", "camila@wingedtycoons.com").strip().lower()


class _PostgresConnection:
    def __init__(self, connection):
        self.connection = connection
        self.cursor = None

    def execute(self, query: str, parameters: tuple = ()):
        if self.cursor:
            self.cursor.close()
        self.cursor = self.connection.cursor(cursor_factory=RealDictCursor)
        self.cursor.execute(query.replace("?", "%s"), parameters)
        return self.cursor

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        if self.cursor:
            self.cursor.close()
        self.connection.close()


def _postgres_dsn() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required for PostgreSQL authentication storage.")
    from services.database_safety import validate_development_database_target

    validate_development_database_target(value, AUTH_ENV)
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://", "postgres://"):
        if value.startswith(prefix):
            return value.replace(prefix, "postgresql://", 1)
    return value


def normalize_role(role: str) -> str:
    normalized = role.strip().upper()
    if normalized == "CUSTOMER":
        return ROLE_CUSTOMER
    if normalized == "INTERNAL":
        return ROLE_INTERNAL
    return normalized


@contextmanager
def _connect() -> Iterator[sqlite3.Connection | _PostgresConnection]:
    if AUTH_STORAGE_BACKEND == "postgres":
        connection = _PostgresConnection(
            postgres_connect(
                _postgres_dsn(),
                connect_timeout=3,
                cursor_factory=RealDictCursor,
            )
        )
    else:
        os.makedirs(os.path.dirname(AUTH_DB_PATH) or ".", exist_ok=True)
        connection = sqlite3.connect(AUTH_DB_PATH)
        connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_auth_db() -> None:
    if AUTH_STORAGE_BACKEND == "postgres":
        with _connect() as connection:
            tables = {
                row["table_name"]
                for row in connection.execute(
                    """SELECT table_name FROM information_schema.tables
                    WHERE table_schema = current_schema()
                    AND table_name IN (
                        'auth_users', 'auth_otp_challenges', 'auth_sessions', 'auth_audit_events'
                    )"""
                ).fetchall()
            }
        expected = {"auth_users", "auth_otp_challenges", "auth_sessions", "auth_audit_events"}
        if tables != expected:
            raise RuntimeError(
                "PostgreSQL authentication schema is not ready; apply the reviewed Alembic migration."
            )
        with _connect() as connection:
            updated = connection.execute(
                """UPDATE auth_users SET role = ?, is_active = TRUE, is_email_verified = TRUE
                WHERE email = ?""",
                ("ROLE_ADMIN", OWNER_ADMIN_EMAIL),
            )
            if updated.rowcount == 0:
                connection.execute(
                    """INSERT INTO auth_users
                    (id,email,full_name,role,is_email_verified,created_at)
                    VALUES (?,?,?,?,?,?)""",
                    (f"INT-{secrets.token_hex(4).upper()}", OWNER_ADMIN_EMAIL, "Camila", "ROLE_ADMIN", True, _now()),
                )
        return

    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL,
                is_email_verified INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_activity_at TEXT
            );
            CREATE TABLE IF NOT EXISTS otp_challenges (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                role TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                request_window_started INTEGER NOT NULL,
                request_count INTEGER NOT NULL DEFAULT 1,
                locked_until INTEGER,
                consumed_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                last_activity_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                action TEXT NOT NULL,
                success INTEGER NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        challenge_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(otp_challenges)")
        }
        if "consumed_at" not in challenge_columns:
            connection.execute("ALTER TABLE otp_challenges ADD COLUMN consumed_at INTEGER")
        existing = connection.execute(
            "SELECT id FROM users WHERE email = ?", ("camila@wingedtycoons.com",)
        ).fetchone()
        if not existing:
            connection.execute(
                """INSERT INTO users
                (id,email,full_name,role,is_email_verified,created_at)
                VALUES (?,?,?,?,?,?)""",
                ("INT-001", "camila@wingedtycoons.com", "Camila", "ROLE_ADMIN", 1, _now()),
            )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table(name: str) -> str:
    return f"auth_{name}" if AUTH_STORAGE_BACKEND == "postgres" else name


def _hash(value: str) -> str:
    return hmac.new(AUTH_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


def _user_row(email: str) -> Optional[sqlite3.Row]:
    with _connect() as connection:
        return connection.execute(
            f"SELECT * FROM {_table('users')} WHERE email = ? AND is_active = TRUE", (email.lower(),)
        ).fetchone()


def request_otp(email: str, role: str, full_name: str = "") -> tuple[str, str]:
    normalized = email.strip().lower()
    role = normalize_role(role)
    email_domain = normalized.rsplit("@", 1)[-1] if "@" in normalized else ""
    if role == ROLE_INTERNAL and email_domain != INTERNAL_DOMAIN:
        raise HTTPException(400, "Internal access is restricted to wingedtycoons.com accounts.")
    if role == ROLE_CUSTOMER and email_domain == INTERNAL_DOMAIN:
        raise HTTPException(400, "Use the internal sign-in for Winged Tycoons staff.")

    now = int(time.time())
    user = _user_row(normalized)

    with _connect() as connection:
        window = connection.execute(
            f"""SELECT COUNT(*) AS count FROM {_table('otp_challenges')}
            WHERE email = ? AND request_window_started > ?""",
            (normalized, now - 3600),
        ).fetchone()["count"]
        if window >= MAX_OTP_REQUESTS_PER_HOUR:
            raise HTTPException(429, "Too many OTP requests. Try again later.")

        if role == "ROLE_CUSTOMER" and not user:
            connection.execute(
                f"""INSERT INTO {_table('users')}
                (id,email,full_name,role,is_email_verified,created_at)
                VALUES (?,?,?,?,?,?)""",
                (f"CUST-{secrets.token_hex(4).upper()}", normalized, full_name or normalized, role, False, _now()),
            )
        if role == ROLE_INTERNAL and not user:
            existing = connection.execute(
                f"SELECT id FROM {_table('users')} WHERE email = ?", (normalized,)
            ).fetchone()
            if existing:
                raise HTTPException(403, "This staff account has been deactivated.")
            connection.execute(
                f"""INSERT INTO {_table('users')}
                (id,email,full_name,role,is_email_verified,created_at)
                VALUES (?,?,?,?,?,?)""",
                (
                    f"INT-{secrets.token_hex(4).upper()}",
                    normalized,
                    full_name or normalized.split("@", 1)[0].replace(".", " ").title(),
                    STAFF_DEFAULT_ROLE,
                    False,
                    _now(),
                ),
            )

        code = f"{secrets.randbelow(1_000_000):06d}"
        challenge_id = secrets.token_urlsafe(18)
        connection.execute(
            f"UPDATE {_table('otp_challenges')} SET consumed_at = ? WHERE email = ? AND consumed_at IS NULL AND expires_at >= ?",
            (now, normalized, now),
        )
        connection.execute(
            f"""INSERT INTO {_table('otp_challenges')}
            (id,email,role,code_hash,expires_at,request_window_started)
            VALUES (?,?,?,?,?,?)""",
            (challenge_id, normalized, role, _hash(code), now + OTP_TTL_SECONDS, now),
        )
        return challenge_id, code


def verify_otp(challenge_id: str, code: str) -> dict:
    now = int(time.time())
    with _connect() as connection:
        if AUTH_STORAGE_BACKEND == "sqlite":
            connection.execute("BEGIN IMMEDIATE")
        challenge = connection.execute(
            f"SELECT * FROM {_table('otp_challenges')} WHERE id = ?"
            f"{' FOR UPDATE' if AUTH_STORAGE_BACKEND == 'postgres' else ''}",
            (challenge_id,),
        ).fetchone()
        if not challenge or challenge["expires_at"] <= now or challenge["consumed_at"] is not None:
            raise HTTPException(401, "OTP is invalid or expired.")
        if (challenge["locked_until"] and challenge["locked_until"] > now) or challenge["attempt_count"] >= MAX_OTP_ATTEMPTS:
            raise HTTPException(429, "OTP verification is locked. Request a new code.")
        if not hmac.compare_digest(challenge["code_hash"], _hash(code.strip())):
            attempt_count = challenge["attempt_count"] + 1
            locked_until = now + OTP_LOCK_SECONDS if attempt_count >= MAX_OTP_ATTEMPTS else None
            connection.execute(
                f"UPDATE {_table('otp_challenges')} SET attempt_count = ?, locked_until = ? WHERE id = ?",
                (attempt_count, locked_until, challenge_id),
            )
            connection.commit()
            if locked_until:
                raise HTTPException(429, "OTP verification is locked. Request a new code.")
            raise HTTPException(401, "OTP is invalid or expired.")

        user = connection.execute(
            f"SELECT * FROM {_table('users')} WHERE email = ? AND is_active = TRUE",
            (challenge["email"],),
        ).fetchone()
        if not user:
            raise HTTPException(401, "Account is unavailable.")
        consumed = connection.execute(
            f"UPDATE {_table('otp_challenges')} SET consumed_at = ? WHERE id = ? AND consumed_at IS NULL",
            (now, challenge_id),
        )
        if consumed.rowcount != 1:
            raise HTTPException(401, "OTP is invalid or expired.")
        connection.execute(
            f"UPDATE {_table('users')} SET is_email_verified = TRUE WHERE id = ?",
            (user["id"],),
        )
        token = secrets.token_urlsafe(32)
        connection.execute(
            f"INSERT INTO {_table('sessions')} VALUES (?,?,?,?)",
            (_hash(token), user["id"], now + SESSION_TTL_SECONDS, now),
        )
        connection.execute(
            f"INSERT INTO {_table('audit_events')} (user_id,action,success,metadata,created_at) VALUES (?,?,?,?,?)",
            (user["id"], "otp_verified", True, challenge["role"], _now()),
        )
        return {"access_token": token, "token_type": "bearer", "role": user["role"], "email": user["email"]}


def init_and_get_user(token_value: str | None) -> dict:
    if not token_value:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")
    now = int(time.time())
    with _connect() as connection:
        row = connection.execute(
            f"""            SELECT u.*, s.expires_at, s.last_activity_at AS session_last_activity
            FROM {_table('sessions')} s JOIN {_table('users')} u ON u.id = s.user_id
            WHERE s.token_hash = ? AND u.is_active = TRUE""",
            (_hash(token_value),),
        ).fetchone()
        if not row or row["expires_at"] < now or row["session_last_activity"] + SESSION_TTL_SECONDS < now:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session.")
        connection.execute(
            f"UPDATE {_table('sessions')} SET last_activity_at = ? WHERE token_hash = ?",
            (now, _hash(token_value)),
        )
        return dict(row)


def revoke_session(token_value: str | None) -> None:
    if not token_value:
        return
    with _connect() as connection:
        connection.execute(
            f"DELETE FROM {_table('sessions')} WHERE token_hash = ?",
            (_hash(token_value),),
        )


def current_user(request: Request) -> dict:
    if request.headers.get("authorization"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Use the secure session cookie to authenticate.")
    return init_and_get_user(request.cookies.get("wt_session"))


def require_roles(*roles: str):
    def dependency(user: dict = Depends(current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions.")
        return user
    return dependency


if AUTH_STORAGE_BACKEND == "sqlite":
    init_auth_db()
