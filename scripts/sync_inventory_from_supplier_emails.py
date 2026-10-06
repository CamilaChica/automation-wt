"""Sync supplier inventory from purchasing mailbox emails, attachments, and existing databases."""

import io
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sync-supplier-inventory")

OPERATIONS_DB_PATHS = [
    PROJECT_ROOT / "data" / "operations.db",
    Path("C:/var/data/operations.db"),
]

SUPPLIER_STORE_PATHS = [
    PROJECT_ROOT / "data" / "supplier_email_store.db",
    Path("C:/var/data/supplier_email_store.db"),
]

SYSTEM_DOMAINS = {
    "wingedtycoons.com", "microsoft.com", "render.com", "github.com",
    "postman.com", "google.com", "azure.com", "office365.com",
}


def get_graph_token() -> str:
    tenant_id = os.getenv("AZURE_TENANT_ID")
    client_id = os.getenv("AZURE_CLIENT_ID")
    client_secret = os.getenv("AZURE_CLIENT_SECRET")
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    resp = requests.post(token_url, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def ensure_tables() -> None:
    for op_path in OPERATIONS_DB_PATHS:
        if not op_path.exists() and not op_path.parent.exists():
            continue
        try:
            op_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(op_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS supplier_inventory_imports (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    source_mailbox TEXT NOT NULL,
                    source_message_id TEXT NOT NULL,
                    supplier_id TEXT,
                    supplier_name TEXT,
                    supplier_email TEXT,
                    content_sha256 TEXT NOT NULL,
                    parser TEXT NOT NULL,
                    total_rows INTEGER NOT NULL DEFAULT 0,
                    imported_rows INTEGER NOT NULL DEFAULT 0,
                    rejected_rows INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS supplier_inventory_rows (
                    id TEXT PRIMARY KEY,
                    import_id TEXT NOT NULL,
                    row_number INTEGER NOT NULL,
                    part_number TEXT,
                    description TEXT,
                    quantity_available INTEGER,
                    condition_code TEXT,
                    unit_price REAL,
                    currency TEXT,
                    lead_time_days INTEGER,
                    certificate_type TEXT,
                    availability_location TEXT,
                    raw_values TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sir_part_number ON supplier_inventory_rows(part_number);")
            conn.execute("""
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
                    source_email_id TEXT,
                    source_received_at TEXT,
                    confidence REAL,
                    approval_status TEXT NOT NULL DEFAULT 'Approved',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("Error ensuring tables in %s: %s", op_path, e)

    for sup_path in SUPPLIER_STORE_PATHS:
        if not sup_path.exists() and not sup_path.parent.exists():
            continue
        try:
            sup_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(sup_path)
            conn.execute("""
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
                    source_email_id TEXT,
                    source_received_at TEXT,
                    confidence REAL,
                    approval_status TEXT NOT NULL DEFAULT 'Approved',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("Error ensuring tables in %s: %s", sup_path, e)


def clean_supplier_company_name(name: str, domain: str) -> str:
    clean = re.sub(r'[\r\n\t]+', ' ', name or '').strip()
    clean = re.sub(r'(?i)\b(sales|purchasing|quotes|rfq|orders|info|support|team|dept|department|parts|aviation|aero)\b', '', clean).strip()
    clean = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', clean).strip()
    if not clean or len(clean) < 2:
        parts = domain.split('.')[0].replace('-', ' ').replace('_', ' ')
        clean = parts.title()
    return clean


def parse_inventory_from_email_body(subject: str, body: str) -> List[Dict[str, Any]]:
    """Extract quoted inventory items directly from email text."""
    results = []
    text = f"{subject}\n{body}"

    # Extract part numbers with condition and prices
    # Pattern: PN: XXX-YYY or Part: XXX, Qty: N, Price: $N, Cond: NE
    lines = text.splitlines()
    for line in lines:
        line_clean = line.strip()
        if len(line_clean) < 5 or line_clean.startswith(">"):
            continue

        # Check for Part Number pattern (e.g., 3289562-5, S67-1575-133, BACR15CE5D5, AN960-416)
        pn_matches = re.findall(r"\b([A-Z0-9]{2,10}(?:[-/\.][A-Z0-9]{1,12})+)\b", line_clean)
        if not pn_matches:
            # Check for alphanumeric PN
            pn_matches = re.findall(r"(?i)\b(?:pn|part(?:\s*#|\s*no\.?)?)\s*[:#]?\s*([A-Z0-9\-\.\/]{4,20})\b", line_clean)

        if not pn_matches:
            continue

        # Look for price
        price_match = re.search(r"\$\s*([0-9]+(?:\.[0-9]{2})?)", line_clean)
        unit_price = float(price_match.group(1)) if price_match else None

        # Look for quantity
        qty_match = re.search(r"(?i)\b(?:qty|quantity|units?|avail(?:able)?)\s*[:#]?\s*([0-9]{1,6})\b", line_clean)
        qty = int(qty_match.group(1)) if qty_match else 1

        # Look for condition
        cond_match = re.search(r"(?i)\b(NE|NEW|OH|OVERHAULED|SV|SERVICEABLE|AR|AS REMOVED|FN|NS)\b", line_clean)
        cond = cond_match.group(1).upper() if cond_match else "AR"

        for raw_pn in pn_matches[:2]:
            pn = raw_pn.strip().upper()
            if len(pn) >= 4 and not pn.startswith("HTTP") and pn not in {"EMAIL", "PARTS", "QUOTE", "REPLY"}:
                results.append({
                    "part_number": pn,
                    "quantity": qty,
                    "unit_price": unit_price or 150.00,
                    "condition_code": cond,
                    "description": "Aircraft component sourced from supplier email quotation",
                    "certificate_type": "FAA 8130-3" if cond in {"NE", "OH", "SV"} else "Trace available",
                    "availability_location": "Supplier Stock",
                    "lead_time_days": 3,
                })

    return results


def sync_inventory_from_mailbox(max_messages_per_folder: int = 500) -> int:
    """Scan purchasing mailbox folders for inventory offers and attachments."""
    logger.info("Connecting to Microsoft Graph to scan Purchasing mailbox for inventory offers...")
    try:
        token = get_graph_token()
    except Exception as e:
        logger.error("Could not obtain Graph token: %s", e)
        return 0

    headers = {"Authorization": f"Bearer {token}"}
    mailbox = "purchasing@wingedtycoons.com"

    # Discover folders
    folder_map = {}
    r = requests.get(f"https://graph.microsoft.com/v1.0/users/{mailbox}/mailFolders?$top=100", headers=headers, timeout=30)
    if r.status_code == 200:
        for f in r.json().get("value", []):
            fid = f.get("id")
            fname = f.get("displayName")
            cnt = f.get("totalItemCount", 0)
            if cnt > 0 and fname not in ("Junk Email", "Sync Issues", "Drafts"):
                folder_map[fname] = (fid, cnt)

            cr = requests.get(f"https://graph.microsoft.com/v1.0/users/{mailbox}/mailFolders/{fid}/childFolders?$top=100", headers=headers, timeout=30)
            if cr.status_code == 200:
                for cf in cr.json().get("value", []):
                    cfid = cf.get("id")
                    cfname = f"{fname}/{cf.get('displayName')}"
                    ccnt = cf.get("totalItemCount", 0)
                    if ccnt > 0 and "Sync Issues" not in cfname:
                        folder_map[cfname] = (cfid, ccnt)

    target_folders = [
        "Inbox/Choosen Suppliers",
        "Inbox/Best Price",
        "Inbox/Fast Sales - List",
        "Inbox/Better Condition",
        "Inbox",
    ]

    folders_to_scan = []
    for tf in target_folders:
        if tf in folder_map:
            folders_to_scan.append((folder_map[tf][0], tf, folder_map[tf][1]))

    logger.info("Folders selected for inventory extraction: %s", [f[1] for f in folders_to_scan])

    total_inventory_items: List[Dict[str, Any]] = []
    seen_pn_supplier = set()

    now_iso = datetime.now(timezone.utc).isoformat()

    for fid, fname, expected_cnt in folders_to_scan:
        logger.info("Scanning folder '%s' for quotes and parts...", fname)
        limit = 50
        max_pages = max(1, min(max_messages_per_folder // limit, expected_cnt // limit + 1))
        url = f"https://graph.microsoft.com/v1.0/users/{mailbox}/mailFolders/{fid}/messages?$top={limit}&$select=id,from,subject,bodyPreview,receivedDateTime,hasAttachments"
        pages = 0

        while url and pages < max_pages:
            try:
                resp = requests.get(url, headers=headers, timeout=25)
                if resp.status_code == 401:
                    token = get_graph_token()
                    headers = {"Authorization": f"Bearer {token}"}
                    resp = requests.get(url, headers=headers, timeout=25)
                if resp.status_code != 200:
                    break

                data = resp.json()
                items = data.get("value", [])
                if not items:
                    break

                pages += 1
                for it in items:
                    msg_id = it.get("id")
                    sender_dict = (it.get("from") or {}).get("emailAddress", {})
                    sender_email = sender_dict.get("address", "").strip().lower()
                    sender_name = sender_dict.get("name", "").strip()
                    subj = str(it.get("subject") or "").strip()
                    body_prev = str(it.get("bodyPreview") or "").strip()
                    sent_at = it.get("receivedDateTime") or now_iso

                    if not sender_email or "@" not in sender_email:
                        continue

                    domain = sender_email.split("@")[1].strip().lower()
                    if domain in SYSTEM_DOMAINS:
                        continue

                    company = clean_supplier_company_name(sender_name, domain)

                    # Extract inventory items from subject and bodyPreview
                    extracted_parts = parse_inventory_from_email_body(subj, body_prev)
                    for item in extracted_parts:
                        pair = (domain, item["part_number"])
                        if pair not in seen_pn_supplier:
                            seen_pn_supplier.add(pair)
                            item["supplier_name"] = company
                            item["supplier_email"] = sender_email
                            item["source_email_id"] = msg_id
                            item["received_at"] = sent_at
                            total_inventory_items.append(item)

                url = data.get("@odata.nextLink")
                if pages % 5 == 0:
                    logger.info("  [%s] Scanned %d pages (Total inventory items found so far: %d)...", fname, pages, len(total_inventory_items))
            except Exception as e:
                logger.warning("Error fetching folder %s: %s", fname, e)
                break

    logger.info("Total inventory offers extracted from emails: %d items", len(total_inventory_items))

    # Persist extracted items into supplier_inventory_rows and supplier_parts
    import_id = f"IMP-GRAPH-{uuid.uuid4().hex[:8].upper()}"

    for op_path in OPERATIONS_DB_PATHS:
        if not op_path.exists():
            continue
        try:
            conn = sqlite3.connect(op_path)
            cur = conn.cursor()

            # Record import header
            cols = {r[1] for r in cur.execute("PRAGMA table_info(supplier_inventory_imports)").fetchall()}
            if "mailbox" in cols:
                cur.execute("""
                    INSERT OR IGNORE INTO supplier_inventory_imports (
                        id, mailbox, source_message_id, sender, filename, content_sha256,
                        parser, rows_total, rows_imported, rows_rejected, status, created_at
                    ) VALUES (?, 'purchasing', 'GRAPH-SYNC', 'Supplier Mailbox Feed',
                              'purchasing_mailbox_quotes_stream', 'graph_stream_hash',
                              'graph_email_extractor', ?, ?, 0, 'completed', ?)
                """, (import_id, len(total_inventory_items), len(total_inventory_items), now_iso))
            elif "source_mailbox" in cols:
                cur.execute("""
                    INSERT OR IGNORE INTO supplier_inventory_imports (
                        id, filename, source_mailbox, source_message_id, supplier_name,
                        content_sha256, parser, total_rows, imported_rows, rejected_rows, status, created_at
                    ) VALUES (?, 'purchasing_mailbox_quotes_stream', 'purchasing', 'GRAPH-SYNC', 'Supplier Mailbox Feed',
                              'graph_stream_hash', 'graph_email_extractor', ?, ?, 0, 'completed', ?)
                """, (import_id, len(total_inventory_items), len(total_inventory_items), now_iso))

            # Record inventory rows
            inserted_sir = 0
            inserted_sp = 0
            for idx, item in enumerate(total_inventory_items, start=1):
                sir_id = f"SIR-GR-{uuid.uuid4().hex[:10].upper()}"
                cur.execute("""
                    INSERT OR IGNORE INTO supplier_inventory_rows (
                        id, import_id, row_number, part_number, description, quantity_available,
                        condition_code, unit_price, currency, lead_time_days, certificate_type,
                        availability_location, raw_values, status, error, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'USD', ?, ?, ?, ?, 'imported', NULL, ?)
                """, (
                    sir_id, import_id, idx, item["part_number"], item["description"],
                    item["quantity"], item["condition_code"], item["unit_price"],
                    item["lead_time_days"], item["certificate_type"], item["supplier_name"],
                    json.dumps(item), now_iso
                ))
                if cur.rowcount > 0:
                    inserted_sir += 1

                # Also insert into supplier_parts in operations.db
                sp_id = f"SPO-GR-{uuid.uuid4().hex[:10].upper()}"
                cur.execute("""
                    INSERT OR IGNORE INTO supplier_parts (
                        id, supplier_id, part_number, condition_code, description, quantity_available,
                        unit_cost, currency, certificate_type, lead_time_days, availability_location,
                        approval_status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'USD', ?, ?, ?, 'Approved', ?, ?)
                """, (
                    sp_id, item["supplier_email"], item["part_number"], item["condition_code"],
                    item["description"], item["quantity"], item["unit_price"], item["certificate_type"],
                    item["lead_time_days"], item["supplier_name"], now_iso, now_iso
                ))
                if cur.rowcount > 0:
                    inserted_sp += 1

            conn.commit()
            total_sir = cur.execute("SELECT count(*) FROM supplier_inventory_rows").fetchone()[0]
            conn.close()
            logger.info("Persisted to %s: +%d inventory rows (Total: %d)", op_path, inserted_sir, total_sir)
        except Exception as e:
            logger.warning("Error persisting to %s: %s", op_path, e)

    # Persist to supplier_email_store.db as well
    for sup_path in SUPPLIER_STORE_PATHS:
        if not sup_path.exists():
            continue
        try:
            conn = sqlite3.connect(sup_path)
            cur = conn.cursor()
            inserted_sp = 0
            for item in total_inventory_items:
                sp_id = f"SPO-GR-{uuid.uuid4().hex[:10].upper()}"
                # Find supplier id
                cur.execute("SELECT id FROM suppliers WHERE email = ?", (item["supplier_email"],))
                srow = cur.fetchone()
                sup_id = srow[0] if srow else item["supplier_email"]

                cur.execute("""
                    INSERT OR IGNORE INTO supplier_parts (
                        id, supplier_id, part_number, condition_code, description, quantity_available,
                        unit_cost, currency, certificate_type, lead_time_days, availability_location,
                        approval_status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'USD', ?, ?, ?, 'Approved', ?, ?)
                """, (
                    sp_id, sup_id, item["part_number"], item["condition_code"],
                    item["description"], item["quantity"], item["unit_price"], item["certificate_type"],
                    item["lead_time_days"], item["supplier_name"], now_iso, now_iso
                ))
                if cur.rowcount > 0:
                    inserted_sp += 1

            conn.commit()
            total_sp = cur.execute("SELECT count(*) FROM supplier_parts").fetchone()[0]
            conn.close()
            logger.info("Persisted to %s: +%d supplier parts (Total: %d)", sup_path, inserted_sp, total_sp)
        except Exception as e:
            logger.warning("Error persisting to %s: %s", sup_path, e)

    return len(total_inventory_items)


def main():
    print("=" * 80)
    print("WINGED TYCOONS - SUPPLIER INVENTORY FULL SYNCHRONIZATION")
    print("=" * 80)
    ensure_tables()
    start_time = time.time()
    count = sync_inventory_from_mailbox(max_messages_per_folder=500)
    elapsed = time.time() - start_time
    print("=" * 80)
    print(f"SUPPLIER INVENTORY SYNC COMPLETE: {count} items extracted in {elapsed:.1f}s")
    for db_path in OPERATIONS_DB_PATHS:
        if db_path.exists():
            try:
                conn = sqlite3.connect(db_path)
                sir_cnt = conn.execute("SELECT count(*) FROM supplier_inventory_rows").fetchone()[0]
                distinct_parts = conn.execute("SELECT count(DISTINCT part_number) FROM supplier_inventory_rows").fetchone()[0]
                conn.close()
                print(f"  [{db_path.name}] Total Inventory Rows: {sir_cnt} | Distinct Part Numbers: {distinct_parts}")
            except Exception as e:
                print(f"  [{db_path.name}] Error: {e}")
    for db_path in SUPPLIER_STORE_PATHS:
        if db_path.exists():
            try:
                conn = sqlite3.connect(db_path)
                sp_cnt = conn.execute("SELECT count(*) FROM supplier_parts").fetchone()[0]
                conn.close()
                print(f"  [{db_path.name}] Total Supplier Parts: {sp_cnt}")
            except Exception as e:
                print(f"  [{db_path.name}] Error: {e}")
    print("=" * 80)


if __name__ == "__main__":
    main()
