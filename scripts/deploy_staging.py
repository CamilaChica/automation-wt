import os
import sqlite3
import sys
from pathlib import Path

from scripts.deployment_common import CheckResult, print_checklist_table, safe_http_request, utc_timestamp
from scripts.preflight_check import REQUIRED_TABLES, run_preflight


def ensure_required_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS inventory_items (
            id TEXT PRIMARY KEY,
            part_number TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            condition_code TEXT NOT NULL,
            certificate_type TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS suppliers (
            id TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            contact_email TEXT,
            approval_status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS csv_ingestion_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT NOT NULL,
            status TEXT NOT NULL,
            processed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS purchase_orders (
            id TEXT PRIMARY KEY,
            vendor_id TEXT NOT NULL,
            part_number TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )


def seed_staging_data(db_path: str) -> CheckResult:
    parent = Path(db_path).parent
    parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        ensure_required_tables(connection)
        connection.execute("DELETE FROM inventory_items")
        connection.execute("DELETE FROM suppliers")
        connection.execute("DELETE FROM csv_ingestion_logs")
        connection.execute("DELETE FROM purchase_orders")
        connection.executemany(
            "INSERT INTO inventory_items (id, part_number, quantity, condition_code, certificate_type) VALUES (?, ?, ?, ?, ?)",
            [
                ("INV-STG-001", "060-1234-00", 8, "NE", "FAA 8130-3"),
                ("INV-STG-002", "456-789-OH", 5, "OH", "EASA Form 1"),
                ("INV-STG-003", "992-1144-00", 3, "AR", "Dual Release"),
            ],
        )
        connection.executemany(
            "INSERT INTO suppliers (id, company_name, contact_email, approval_status) VALUES (?, ?, ?, ?)",
            [
                ("SUP-STG-001", "Apex Aero Components LLC", "quotes@apexaero.com", "Approved"),
                ("SUP-STG-002", "Vanguard Aviation Spares Inc.", "procurement@vanguardspares.com", "Approved"),
            ],
        )
        connection.execute(
            "INSERT INTO csv_ingestion_logs (source_name, status, processed_at) VALUES (?, ?, ?)",
            ("staging_seed_inventory.csv", "success", utc_timestamp()),
        )
        connection.execute(
            "INSERT INTO purchase_orders (id, vendor_id, part_number, quantity, created_at) VALUES (?, ?, ?, ?, ?)",
            ("PO-STG-001", "SUP-STG-001", "060-1234-00", 2, utc_timestamp()),
        )
    return CheckResult("Staging seed", True, f"Seeded required data in {db_path}")


def trigger_render_staging_deploy() -> CheckResult:
    hook = os.getenv("RENDER_STAGING_DEPLOY_HOOK") or os.getenv("RENDER_DEPLOY_HOOK")
    if not hook:
        return CheckResult("Render staging deploy", False, "Missing RENDER_STAGING_DEPLOY_HOOK (or RENDER_DEPLOY_HOOK)")
    ok, details = safe_http_request("POST", hook, timeout_seconds=20)
    return CheckResult("Render staging deploy", ok, details if ok else f"Deploy hook call failed: {details}")


def print_test_credentials() -> None:
    customer = os.getenv("STAGING_CUSTOMER_EMAIL", "customer-test@example.com")
    sales = os.getenv("STAGING_SALES_EMAIL", "sales@wingedtycoons.com")
    procurement = os.getenv("STAGING_PROCUREMENT_EMAIL", "purchasing@wingedtycoons.com")
    admin = os.getenv("STAGING_ADMIN_EMAIL", "camila@wingedtycoons.com")
    print("\nStaging role credentials (OTP sign-in):")
    print(f"  Customer:    {customer}")
    print(f"  Sales:       {sales}")
    print(f"  Procurement: {procurement}")
    print(f"  Admin:       {admin}")


def await_manual_uat_gate() -> int:
    prompt = (
        "\nManual staging UAT checkpoint:\n"
        "Run RFQ -> signature/compliance -> auto-quote -> vendor PO checks.\n"
        "Type APPROVE_STAGING to close the staging run: "
    )
    token = input(prompt).strip()
    if token != "APPROVE_STAGING":
        print("Staging run stopped: approval token not provided.")
        return 1
    print("Staging approval acknowledged.")
    return 0


def main() -> int:
    preflight_code = run_preflight()
    if preflight_code != 0:
        print("Aborting staging deploy: pre-flight checks failed.")
        return preflight_code

    db_path = os.getenv("MIGRATION_SQLITE_PATH", "/var/data/app.db")
    checks = [seed_staging_data(db_path), trigger_render_staging_deploy()]
    print_checklist_table("Staging Deployment Tasks", checks)
    if not all(item.passed for item in checks):
        return 1

    staging_url = os.getenv("STAGING_APP_URL", "https://staging-app.onrender.com")
    print(f"\nStaging URL: {staging_url}")
    print_test_credentials()
    return await_manual_uat_gate()


if __name__ == "__main__":
    sys.exit(main())
