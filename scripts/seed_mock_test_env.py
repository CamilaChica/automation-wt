"""
Seed and Reset Script for Winged Tycoons Mock Testing Environment

This script seeds mock team members (internal roles) and mock customer accounts
into the authentication database (data/winged_tycoons_auth.db) and verifies
backend connectivity.

Usage:
    python scripts/seed_mock_test_env.py [--reset]
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

AUTH_DB_PATH = os.path.join(PROJECT_ROOT, "data", "winged_tycoons_auth.db")

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def get_db_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(AUTH_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
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

def reset_db(conn: sqlite3.Connection) -> None:
    print("[*] Resetting mock testing database...")
    conn.execute("DELETE FROM sessions")
    conn.execute("DELETE FROM otp_challenges")
    conn.execute("DELETE FROM audit_events")
    conn.execute("DELETE FROM users")
    conn.commit()
    print("[+] Database reset complete.")

def seed_mock_users(conn: sqlite3.Connection) -> None:
    print("[*] Seeding mock team members and mock customers...")

    # Internal Team Members (@wingedtycoons.com)
    mock_team_members = [
        ("INT-001", "camila@wingedtycoons.com", "Camila (Admin)", "ROLE_ADMIN", 1),
        ("INT-002", "alex.sales@wingedtycoons.com", "Alex Sales (Sales Rep)", "ROLE_INTERNAL", 1),
        ("INT-003", "sarah.procurement@wingedtycoons.com", "Sarah Procurement (Sourcing Lead)", "ROLE_INTERNAL", 1),
        ("INT-004", "dave.compliance@wingedtycoons.com", "Dave Compliance (Quality Manager)", "ROLE_INTERNAL", 1),
    ]

    # Mock Customer Accounts
    mock_customers = [
        ("CUST-DELTA", "procurement@delta-mro.com", "Delta MRO Services", "ROLE_CUSTOMER", 1),
        ("CUST-SKYWEST", "buyer@skywest.com", "SkyWest Airlines Procurement", "ROLE_CUSTOMER", 1),
        ("CUST-AEROJET", "spares@aerojet.com", "AeroJet Maintenance", "ROLE_CUSTOMER", 1),
        ("CUST-GLOBAL", "parts@globalair.com", "Global Air Support", "ROLE_CUSTOMER", 1),
    ]

    all_users = mock_team_members + mock_customers
    inserted_count = 0
    updated_count = 0

    for user_id, email, full_name, role, verified in all_users:
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE users SET full_name = ?, role = ?, is_email_verified = ?, is_active = 1 WHERE email = ?",
                (full_name, role, verified, email)
            )
            updated_count += 1
        else:
            conn.execute(
                """INSERT INTO users (id, email, full_name, role, is_email_verified, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, email, full_name, role, verified, _now())
            )
            inserted_count += 1

    conn.commit()
    print(f"[+] Seeding finished: {inserted_count} inserted, {updated_count} updated.")

def list_users(conn: sqlite3.Connection) -> None:
    print("\n--- Provisioned Mock Users ---")
    rows = conn.execute("SELECT id, email, full_name, role, is_email_verified FROM users").fetchall()
    print(f"{'ID':<12} | {'Role':<15} | {'Email':<35} | {'Full Name'}")
    print("-" * 80)
    for row in rows:
        print(f"{row['id']:<12} | {row['role']:<15} | {row['email']:<35} | {row['full_name']}")

def main():
    parser = argparse.ArgumentParser(description="Seed Winged Tycoons mock testing environment.")
    parser.add_argument("--reset", action="store_true", help="Reset existing auth users and sessions before seeding.")
    args = parser.parse_args()

    conn = get_db_connection()
    try:
        init_tables(conn)
        if args.reset:
            reset_db(conn)
        seed_mock_users(conn)
        list_users(conn)
        print("\n[+] Mock testing environment successfully seeded!")
        print("    Note: Run backend with WT_AUTH_ENV=development to view development OTPs in responses/UI.")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
