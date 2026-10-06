"""Sync and backfill client quotation history from operational databases and Graph sent items."""

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
logger = logging.getLogger("sync-client-quote-history")

SQLITE_DB_PATHS = [
    PROJECT_ROOT / "data" / "operations.db",
    Path("C:/var/data/operations.db"),
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


def ensure_client_quote_history_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS client_quote_history (
            id TEXT PRIMARY KEY,
            client_email TEXT NOT NULL,
            client_name TEXT,
            company_name TEXT,
            quote_number TEXT NOT NULL,
            rfq_id TEXT,
            part_number TEXT NOT NULL,
            normalized_part_number TEXT NOT NULL,
            description TEXT,
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_price REAL NOT NULL,
            total_price REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'USD',
            condition TEXT,
            certification TEXT,
            lead_time TEXT,
            valid_until TEXT,
            status TEXT NOT NULL DEFAULT 'SENT',
            email_subject TEXT,
            email_body TEXT,
            attachments TEXT,
            sent_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cqh_client_email ON client_quote_history(client_email);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cqh_part_number ON client_quote_history(part_number);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cqh_quote_number ON client_quote_history(quote_number);")
    conn.commit()


def backfill_from_database() -> int:
    """Consolidate from customer_quotes, customer_quote_items, rfqs, and customers."""
    total_added = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for db_path in SQLITE_DB_PATHS:
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            ensure_client_quote_history_table(conn)
            cur = conn.cursor()

            query = """
                SELECT 
                    c.email AS client_email,
                    COALESCE(c.contact_name, c.company_name) AS client_name,
                    c.company_name,
                    cq.quote_number,
                    cq.rfq_id,
                    cqi.part_number,
                    cqi.description,
                    cqi.quantity,
                    cqi.unit_price,
                    (cqi.unit_price * cqi.quantity) AS total_price,
                    cqi.condition,
                    cqi.certification,
                    cqi.lead_time,
                    cq.valid_until,
                    cq.status,
                    cq.created_at AS sent_at
                FROM customer_quotes cq
                JOIN rfqs r ON cq.rfq_id = r.id
                JOIN customers c ON r.customer_id = c.id
                JOIN customer_quote_items cqi ON cqi.quote_id = cq.id
                WHERE c.email IS NOT NULL AND cqi.part_number IS NOT NULL
            """
            rows = cur.execute(query).fetchall()
            added = 0
            for r in rows:
                qid = f"CQH-{uuid.uuid4().hex[:12].upper()}"
                norm_pn = re.sub(r"[^A-Z0-9]", "", (r["part_number"] or "").upper())
                cur.execute("""
                    INSERT OR IGNORE INTO client_quote_history (
                        id, client_email, client_name, company_name, quote_number, rfq_id,
                        part_number, normalized_part_number, description, quantity, unit_price,
                        total_price, currency, condition, certification, lead_time, valid_until,
                        status, sent_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'USD', ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    qid, r["client_email"].lower().strip(), r["client_name"], r["company_name"],
                    r["quote_number"], r["rfq_id"], r["part_number"], norm_pn, r["description"],
                    r["quantity"] or 1, r["unit_price"] or 0.0, r["total_price"] or 0.0,
                    r["condition"] or "AR", r["certification"] or "FAA 8130-3", str(r["lead_time"] or "Stock"),
                    r["valid_until"], r["status"] or "SENT", r["sent_at"] or now_iso, now_iso, now_iso
                ))
                if cur.rowcount > 0:
                    added += 1

            conn.commit()
            total_count = cur.execute("SELECT count(*) FROM client_quote_history").fetchone()[0]
            conn.close()
            logger.info("Database backfill on %s: +%d added (Total in table: %d)", db_path, added, total_count)
            total_added += added
        except Exception as e:
            logger.warning("Error backfilling on %s: %s", db_path, e)

    return total_added


def sync_sent_quotes_from_graph(max_pages: int = 100) -> int:
    """Scan sent items in sales and quotes mailboxes to capture all formal client quotes sent."""
    logger.info("Connecting to Microsoft Graph to scan Sent Items for customer quotations...")
    try:
        token = get_graph_token()
    except Exception as e:
        logger.error("Could not obtain Graph token: %s", e)
        return 0

    headers = {"Authorization": f"Bearer {token}"}
    mailboxes = ["sales@wingedtycoons.com", "quotes@wingedtycoons.com"]
    total_quotes_found = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    quote_records: List[Dict[str, Any]] = []

    for mailbox in mailboxes:
        logger.info("Scanning Sent Items for %s...", mailbox)
        url = f"https://graph.microsoft.com/v1.0/users/{mailbox}/mailFolders/sentitems/messages?$top=50&$select=subject,toRecipients,receivedDateTime,bodyPreview,body"
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
                    subj = str(it.get("subject") or "").strip()
                    sent_at = it.get("receivedDateTime") or now_iso
                    recips = it.get("toRecipients") or []
                    preview = str(it.get("bodyPreview") or "")
                    body_content = (it.get("body") or {}).get("content", "") or preview

                    # Identify if this email represents a quotation sent to client
                    # Examples: "Winged Tycoons quotation QTE-C56C23", "Quote QTE-...", "TEST-QUOTE-5"
                    quote_num_match = re.search(r"(?i)\b(?:quotation|quote)\s*(?:#|no\.?)?\s*([A-Z0-9\-_]{4,20})\b", subj)
                    if not quote_num_match:
                        quote_num_match = re.search(r"(?i)\b(QTE-[A-Z0-9]{4,10})\b", subj) or re.search(r"(?i)\b(TEST-QUOTE-\d+)\b", subj)

                    quote_number = quote_num_match.group(1).upper() if quote_num_match else None
                    if not quote_number and not ("quotation" in subj.lower() or "quote" in subj.lower()):
                        continue

                    if not quote_number:
                        quote_number = f"QTE-SENT-{abs(hash(subj + str(sent_at))) % 1000000:06d}"

                    # Detect part number from subject or body preview
                    # e.g., "Re: ITAR-9000-AR", "BACR15CE5D5", "ACT-7788-AR"
                    pn_match = re.search(r"(?i)(?:part|pn|p/n|re:)\s*#?\s*([A-Z0-9][A-Z0-9\-\.\/]{3,24})", subj)
                    part_number = pn_match.group(1).upper() if pn_match else None
                    if not part_number:
                        body_pn_match = re.search(r"(?i)(?:part\s*(?:number|#|no\.?)|p/n)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-\.\/]{3,24})", body_content)
                        if body_pn_match:
                            part_number = body_pn_match.group(1).upper()
                    if not part_number:
                        part_number = "AIRCRAFT-PARTS"

                    norm_pn = re.sub(r"[^A-Z0-9]", "", part_number)

                    # Extract price if present
                    price_match = re.search(r"\$\s*([0-9]+(?:\.[0-9]{2})?)", body_content)
                    unit_price = float(price_match.group(1)) if price_match else 0.0

                    # Extract condition
                    cond_match = re.search(r"(?i)\b(NE|NEW|OH|OVERHAULED|SV|SERVICEABLE|AR|AS REMOVED|FN)\b", body_content)
                    condition = cond_match.group(1).upper() if cond_match else "AR"

                    for r in recips:
                        addr = r.get("emailAddress", {}).get("address", "").strip().lower()
                        name = r.get("emailAddress", {}).get("name", "").strip()
                        if addr and "@" in addr:
                            domain = addr.split("@")[1].strip().lower()
                            if domain not in SYSTEM_DOMAINS:
                                quote_records.append({
                                    "client_email": addr,
                                    "client_name": name,
                                    "company_name": domain.split(".")[0].capitalize(),
                                    "quote_number": quote_number,
                                    "part_number": part_number,
                                    "normalized_part_number": norm_pn,
                                    "unit_price": unit_price,
                                    "condition": condition,
                                    "sent_at": sent_at,
                                    "email_subject": subj,
                                })
                                total_quotes_found += 1

                url = data.get("@odata.nextLink")
                if pages % 10 == 0:
                    logger.info("  Scanned %d pages in %s (%d quote dispatches recognized)...", pages, mailbox, len(quote_records))
            except Exception as e:
                logger.warning("Error fetching sent items in %s: %s", mailbox, e)
                break

    # Persist all discovered sent quotes into client_quote_history across all DBs
    logger.info("Discovered %d sent quote references to clients from Graph.", len(quote_records))
    for db_path in SQLITE_DB_PATHS:
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(db_path)
            ensure_client_quote_history_table(conn)
            cur = conn.cursor()
            inserted = 0
            for q in quote_records:
                qid = f"CQH-GR-{uuid.uuid4().hex[:10].upper()}"
                cur.execute("""
                    INSERT OR IGNORE INTO client_quote_history (
                        id, client_email, client_name, company_name, quote_number,
                        part_number, normalized_part_number, description, quantity, unit_price,
                        total_price, currency, condition, certification, lead_time, status,
                        email_subject, sent_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Quoted via Winged Tycoons Sales Team', 1, ?, ?, 'USD', ?, 'FAA 8130-3', 'Stock', 'SENT', ?, ?, ?, ?)
                """, (
                    qid, q["client_email"], q["client_name"], q["company_name"], q["quote_number"],
                    q["part_number"], q["normalized_part_number"], q["unit_price"], q["unit_price"],
                    q["condition"], q["email_subject"], q["sent_at"], now_iso, now_iso
                ))
                if cur.rowcount > 0:
                    inserted += 1

            conn.commit()
            total_now = cur.execute("SELECT count(*) FROM client_quote_history").fetchone()[0]
            conn.close()
            logger.info("Persisted to %s: +%d new sent quotes (Total quote history: %d)", db_path, inserted, total_now)
        except Exception as e:
            logger.warning("Failed persisting to %s: %s", db_path, e)

    return total_quotes_found


def main():
    print("=" * 80)
    print("WINGED TYCOONS - CLIENT QUOTATION HISTORY FULL SYNCHRONIZATION")
    print("=" * 80)
    start_time = time.time()
    db_count = backfill_from_database()
    graph_count = sync_sent_quotes_from_graph(max_pages=80)
    elapsed = time.time() - start_time
    print("=" * 80)
    print(f"CLIENT QUOTE HISTORY SYNC COMPLETE: in {elapsed:.1f}s")
    for db_path in SQLITE_DB_PATHS:
        if db_path.exists():
            try:
                conn = sqlite3.connect(db_path)
                cnt = conn.execute("SELECT count(*) FROM client_quote_history").fetchone()[0]
                distinct_clients = conn.execute("SELECT count(DISTINCT client_email) FROM client_quote_history").fetchone()[0]
                distinct_parts = conn.execute("SELECT count(DISTINCT normalized_part_number) FROM client_quote_history").fetchone()[0]
                conn.close()
                print(f"  [{db_path.name}] Total Quotes: {cnt} | Distinct Clients: {distinct_clients} | Distinct Parts Quoted: {distinct_parts}")
            except Exception as e:
                print(f"  [{db_path.name}] Error: {e}")
    print("=" * 80)


if __name__ == "__main__":
    main()
