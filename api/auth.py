import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

AUTH_DB_PATH = os.getenv("WT_AUTH_DB", "data/winged_tycoons_auth.db")
INTERNAL_DOMAIN = "wingedtycoons.com"
OTP_TTL_SECONDS = 5 * 60
SESSION_TTL_SECONDS = 8 * 60 * 60
MAX_OTP_REQUESTS_PER_HOUR = 3
MAX_OTP_ATTEMPTS = 5
AUTH_SECRET = os.getenv("WT_AUTH_SECRET", "development-only-change-this-secret")
security = HTTPBearer(auto_error=False)


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(AUTH_DB_PATH) or ".", exist_ok=True)
    connection = sqlite3.connect(AUTH_DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_auth_db() -> None:
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
                locked_until INTEGER
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


def _hash(value: str) -> str:
    return hmac.new(AUTH_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


def _user_row(email: str) -> Optional[sqlite3.Row]:
    with _connect() as connection:
        return connection.execute(
            "SELECT * FROM users WHERE email = ? AND is_active = 1", (email.lower(),)
        ).fetchone()


def request_otp(email: str, role: str, full_name: str = "") -> tuple[str, str]:
    normalized = email.strip().lower()
    if role == "ROLE_INTERNAL" and not normalized.endswith(f"@{INTERNAL_DOMAIN}"):
        raise HTTPException(400, "Internal users must use a Winged Tycoons email.")
    if role == "ROLE_CUSTOMER" and normalized.endswith(f"@{INTERNAL_DOMAIN}"):
        raise HTTPException(400, "Use the internal sign-in for Winged Tycoons staff.")

    now = int(time.time())
    user = _user_row(normalized)
    if role == "ROLE_INTERNAL" and (not user or not user["is_email_verified"]):
        raise HTTPException(403, "Internal access requires an approved staff account.")

    with _connect() as connection:
        window = connection.execute(
            """SELECT COUNT(*) AS count FROM otp_challenges
            WHERE email = ? AND request_window_started > ?""",
            (normalized, now - 3600),
        ).fetchone()["count"]
        if window >= MAX_OTP_REQUESTS_PER_HOUR:
            raise HTTPException(429, "Too many OTP requests. Try again later.")

        if role == "ROLE_CUSTOMER" and not user:
            connection.execute(
                """INSERT INTO users
                (id,email,full_name,role,is_email_verified,created_at)
                VALUES (?,?,?,?,?,?)""",
                (f"CUST-{secrets.token_hex(4).upper()}", normalized, full_name or normalized, role, 0, _now()),
            )

        code = f"{secrets.randbelow(1_000_000):06d}"
        challenge_id = secrets.token_urlsafe(18)
        connection.execute(
            """INSERT INTO otp_challenges
            (id,email,role,code_hash,expires_at,request_window_started)
            VALUES (?,?,?,?,?,?)""",
            (challenge_id, normalized, role, _hash(code), now + OTP_TTL_SECONDS, now),
        )
        return challenge_id, code


def verify_otp(challenge_id: str, code: str) -> dict:
    now = int(time.time())
    with _connect() as connection:
        challenge = connection.execute(
            "SELECT * FROM otp_challenges WHERE id = ?", (challenge_id,)
        ).fetchone()
        if not challenge or challenge["expires_at"] < now or (
            challenge["locked_until"] and challenge["locked_until"] > now
        ):
            raise HTTPException(401, "OTP is invalid or expired.")
        if challenge["attempt_count"] >= MAX_OTP_ATTEMPTS:
            raise HTTPException(429, "OTP verification is locked. Request a new code.")
        if not hmac.compare_digest(challenge["code_hash"], _hash(code.strip())):
            connection.execute(
                "UPDATE otp_challenges SET attempt_count = attempt_count + 1 WHERE id = ?",
                (challenge_id,),
            )
            raise HTTPException(401, "OTP is invalid or expired.")

        user = connection.execute(
            "SELECT * FROM users WHERE email = ? AND is_active = 1", (challenge["email"],)
        ).fetchone()
        if not user:
            raise HTTPException(401, "Account is unavailable.")
        connection.execute("UPDATE users SET is_email_verified = 1 WHERE id = ?", (user["id"],))
        token = secrets.token_urlsafe(32)
        connection.execute(
            "INSERT INTO sessions VALUES (?,?,?,?)",
            (_hash(token), user["id"], now + SESSION_TTL_SECONDS, now),
        )
        connection.execute(
            "INSERT INTO audit_events (user_id,action,success,metadata,created_at) VALUES (?,?,?,?,?)",
            (user["id"], "otp_verified", 1, challenge["role"], _now()),
        )
        return {"access_token": token, "token_type": "bearer", "role": user["role"], "email": user["email"]}


def init_and_get_user(credentials: HTTPAuthorizationCredentials | None) -> dict:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")
    now = int(time.time())
    with _connect() as connection:
        row = connection.execute(
            """            SELECT u.*, s.expires_at, s.last_activity_at AS session_last_activity
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND u.is_active = 1""",
            (_hash(credentials.credentials),),
        ).fetchone()
        if not row or row["expires_at"] < now or row["session_last_activity"] + SESSION_TTL_SECONDS < now:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session.")
        connection.execute(
            "UPDATE sessions SET last_activity_at = ? WHERE token_hash = ?",
            (now, _hash(credentials.credentials)),
        )
        return dict(row)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict:
    return init_and_get_user(credentials)


def require_roles(*roles: str):
    def dependency(user: dict = Depends(current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions.")
        return user
    return dependency


init_auth_db()
