"""Copy SQLite auth users to PostgreSQL without migrating OTPs or sessions."""

import argparse
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

import psycopg2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        default=Path(os.getenv("WT_AUTH_DB", "data/winged_tycoons_auth.db")),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Copy approved user records; without this option, only report row counts.",
    )
    parser.add_argument(
        "--invalidate-existing-auth",
        action="store_true",
        help="During apply, invalidate all target OTP challenges and sessions.",
    )
    parser.add_argument(
        "--confirm-target",
        action="store_true",
        help="Confirm the PostgreSQL host/database reviewed during the dry run.",
    )
    args = parser.parse_args()

    if args.apply and not args.invalidate_existing_auth:
        parser.error("--apply requires --invalidate-existing-auth to force a clean auth cutover.")
    if args.apply and not args.confirm_target:
        parser.error("--apply requires --confirm-target after reviewing the displayed target.")
    if not args.sqlite_path.is_file():
        parser.error(f"SQLite auth database does not exist: {args.sqlite_path}")

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        parser.error("DATABASE_URL must point to the reviewed PostgreSQL target.")
    if os.getenv("WT_AUTH_ENV", "development").strip().lower() != "production":
        parser.error("Set WT_AUTH_ENV=production explicitly before running the auth cutover.")
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://", "postgres://"):
        if database_url.startswith(prefix):
            database_url = database_url.replace(prefix, "postgresql://", 1)
            break
    target = urlsplit(database_url)
    print(f"PostgreSQL target host: {target.hostname or '(unknown)'}")
    print(f"PostgreSQL target database: {(target.path or '').lstrip('/') or '(unknown)'}")
    if args.apply and (not target.hostname or not target.path.strip("/")):
        parser.error("DATABASE_URL must identify both a PostgreSQL host and database.")

    with closing(sqlite3.connect(args.sqlite_path)) as source:
        source.row_factory = sqlite3.Row
        users = source.execute(
            """SELECT id, email, full_name, role, is_email_verified, is_active,
                      created_at, last_activity_at
            FROM users
            ORDER BY email"""
        ).fetchall()

    if not args.apply:
        print(f"Dry run: {len(users)} SQLite auth user records would be considered.")
        print("No OTP challenges, sessions, or data were changed.")
        return

    imported = 0
    with closing(psycopg2.connect(database_url, connect_timeout=5)) as target:
        with target:
            with target.cursor() as cursor:
                cursor.execute(
                    """SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = current_schema() AND table_name = 'auth_users'"""
                )
                if cursor.fetchone()[0] != 1:
                    raise RuntimeError("PostgreSQL auth schema is missing; apply the reviewed Alembic migration first.")

                cursor.execute("DELETE FROM auth_sessions")
                cursor.execute("DELETE FROM auth_otp_challenges")
                for user in users:
                    cursor.execute(
                        """INSERT INTO auth_users
                        (id, email, full_name, role, is_email_verified, is_active, created_at, last_activity_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (email) DO NOTHING
                        RETURNING id""",
                        (
                            user["id"],
                            user["email"],
                            user["full_name"],
                            user["role"],
                            bool(user["is_email_verified"]),
                            bool(user["is_active"]),
                            user["created_at"],
                            user["last_activity_at"],
                        ),
                    )
                    inserted = cursor.fetchone()
                    if inserted:
                        imported += 1
                        continue

                    cursor.execute(
                        """SELECT id, full_name, role, is_email_verified, is_active
                        FROM auth_users WHERE email = %s""",
                        (user["email"],),
                    )
                    existing = cursor.fetchone()
                    expected = (
                        user["id"],
                        user["full_name"],
                        user["role"],
                        bool(user["is_email_verified"]),
                        bool(user["is_active"]),
                    )
                    if not existing or tuple(existing) != expected:
                        raise RuntimeError(
                            "An existing PostgreSQL auth user conflicts with the SQLite source; "
                            "review and reconcile it manually before retrying."
                        )

    with closing(sqlite3.connect(args.sqlite_path)) as source:
        with source:
            source.execute("DELETE FROM sessions")
            source.execute("DELETE FROM otp_challenges")

    print(f"Auth cutover completed: {imported} user records imported.")
    print("Source and target OTP challenges and sessions were invalidated; none were copied.")


if __name__ == "__main__":
    main()
