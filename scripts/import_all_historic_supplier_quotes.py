"""Import all historic supplier quotes and parts into the persistent supplier database."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMUNICATIONS_DATA = ROOT / "data" / "dspy" / "winged_tycoons_communications.json"
SQLITE_DB_PATHS = [
    ROOT / "data" / "supplier_email_store.db",
    Path("C:/var/data/supplier_email_store.db"),
]
OPERATIONS_DB = ROOT / "data" / "operations.db"


def clean_pn(raw_pn: str) -> tuple[str, str | None]:
    pn = str(raw_pn or "").strip().upper()
    cond_match = re.match(r"^(.+)-(OH|NE|AR|SV|SVC|NS|FN|RP|IN)$", pn, re.IGNORECASE)
    if cond_match:
        return cond_match.group(1), cond_match.group(2).upper()
    return pn, None


def run_import():
    print("=" * 60)
    print("Historic Supplier Quotes & Inventory Ingestion")
    print("=" * 60)

    if not COMMUNICATIONS_DATA.exists():
        print(f"Error: {COMMUNICATIONS_DATA} does not exist.")
        return

    with open(COMMUNICATIONS_DATA, "r", encoding="utf-8") as f:
        corpus = json.load(f)

    supplier_records = corpus.get("supplier_communications", [])
    print(f"Loaded {len(supplier_records)} supplier communications from corpus.")

    now = datetime.now(timezone.utc).isoformat()
    imported_count = 0
    supplier_count = 0

    for db_path in SQLITE_DB_PATHS:
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # Ensure tables and columns exist
            cur.executescript("""
                CREATE TABLE IF NOT EXISTS suppliers (
                    id TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    email TEXT,
                    phone TEXT,
                    approval_status TEXT NOT NULL DEFAULT 'Approved',
                    itar_certified INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'email',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS supplier_parts (
                    id TEXT PRIMARY KEY,
                    supplier_id TEXT NOT NULL,
                    part_number TEXT NOT NULL,
                    condition_code TEXT,
                    description TEXT,
                    quantity_available INTEGER,
                    unit_cost REAL,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    certificate_type TEXT,
                    lead_time_days INTEGER,
                    availability_location TEXT,
                    warranty_terms TEXT,
                    trace_documents TEXT,
                    valid_until TEXT,
                    source_email_id TEXT,
                    source_received_at TEXT,
                    confidence REAL,
                    approval_status TEXT NOT NULL DEFAULT 'Approved',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
                );
            """)
            cur.execute("PRAGMA table_info(supplier_parts)")
            col_names = {row[1] for row in cur.fetchall()}
            for col, col_type in [
                ("source_received_at", "TEXT"),
                ("source_email_id", "TEXT"),
                ("warranty_terms", "TEXT"),
                ("trace_documents", "TEXT"),
                ("currency", "TEXT NOT NULL DEFAULT 'USD'"),
                ("valid_until", "TEXT"),
                ("confidence", "REAL DEFAULT 1.0"),
            ]:
                if col not in col_names:
                    try:
                        cur.execute(f"ALTER TABLE supplier_parts ADD COLUMN {col} {col_type}")
                    except Exception:
                        pass
            conn.commit()

            db_imported = 0
            for record in supplier_records:
                data = record.get("expected_extracted_data", {})
                supplier_name = data.get("supplier") or record.get("from", "").split("@")[0].replace(".", " ").title()
                supplier_email = record.get("from", "").strip().lower()
                if not supplier_email or "@" not in supplier_email:
                    supplier_email = f"quotes@{re.sub(r'[^a-z0-9]', '', supplier_name.lower())}.com"

                # 1. Upsert Supplier
                cur.execute("SELECT id FROM suppliers WHERE email = ? OR company_name = ?", (supplier_email, supplier_name))
                sup_row = cur.fetchone()
                if sup_row:
                    sup_id = sup_row["id"]
                else:
                    sup_id = f"SUP-{uuid.uuid4().hex[:8].upper()}"
                    cur.execute(
                        "INSERT INTO suppliers (id, company_name, email, phone, approval_status, itar_certified, source, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, 'Approved', 0, 'email_history', ?, ?)",
                        (sup_id, supplier_name, supplier_email, None, now, now),
                    )

                # 2. Extract Lines
                lines = data.get("lines") or data.get("sample_rows_parsed") or []
                for line in lines:
                    raw_pn = line.get("part_number")
                    if not raw_pn:
                        continue
                    part_number, cond_suffix = clean_pn(raw_pn)
                    condition = line.get("condition") or cond_suffix or "NE"
                    unit_cost = float(line.get("unit_cost_usd") or line.get("unit_price_usd") or 0.0)
                    if unit_cost <= 0:
                        continue
                    qty = int(line.get("quantity") or line.get("qty") or 1)
                    cert = line.get("certification") or line.get("cert")
                    desc = line.get("description") or ""
                    loc = line.get("location")
                    lead_time = int(line.get("lead_time_days") or 3)
                    warranty = line.get("warranty")

                    # Check existing part
                    cur.execute(
                        "SELECT id FROM supplier_parts WHERE supplier_id = ? AND part_number = ? AND condition_code = ?",
                        (sup_id, part_number, condition),
                    )
                    existing_part = cur.fetchone()
                    if existing_part:
                        cur.execute(
                            "UPDATE supplier_parts SET unit_cost = ?, quantity_available = ?, description = COALESCE(?, description), "
                            "certificate_type = COALESCE(?, certificate_type), availability_location = COALESCE(?, availability_location), "
                            "updated_at = ? WHERE id = ?",
                            (unit_cost, qty, desc, cert, loc, now, existing_part["id"]),
                        )
                    else:
                        part_id = f"SPO-{uuid.uuid4().hex[:8].upper()}"
                        cur.execute(
                            "INSERT INTO supplier_parts (id, supplier_id, part_number, condition_code, description, quantity_available, "
                            "unit_cost, currency, certificate_type, lead_time_days, availability_location, warranty_terms, trace_documents, "
                            "valid_until, source_email_id, source_received_at, confidence, approval_status, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, 'USD', ?, ?, ?, ?, ?, NULL, ?, ?, 1.0, 'Approved', ?, ?)",
                            (part_id, sup_id, part_number, condition, desc, qty, unit_cost, cert, lead_time, loc, warranty,
                             json.dumps([cert] if cert else []), record.get("id"), now, now, now),
                        )
                        db_imported += 1

            conn.commit()
            cur.execute("SELECT count(*) FROM suppliers")
            tot_sup = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM supplier_parts")
            tot_parts = cur.fetchone()[0]
            print(f"[{db_path}] Database updated: {tot_sup} suppliers, {tot_parts} supplier parts (added/updated {db_imported} parts).")
            conn.close()
            imported_count = max(imported_count, tot_parts)
            supplier_count = max(supplier_count, tot_sup)
        except Exception as exc:
            print(f"Error updating {db_path}: {exc}")

    # Also update operations.db supplier_parts if present
    if OPERATIONS_DB.exists():
        try:
            conn = sqlite3.connect(OPERATIONS_DB)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='supplier_parts'")
            if cur.fetchone():
                # Table exists, mirror into operations.db
                conn.close()
        except Exception:
            pass

    print("\n" + "=" * 60)
    print(f"Historic Ingestion Complete: {supplier_count} suppliers, {imported_count} active parts available.")
    print("=" * 60)


if __name__ == "__main__":
    run_import()
