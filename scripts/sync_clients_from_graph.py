"""High-speed synchronization of all client contacts from mailboxes (sales, rfq, quotes) and operations database."""

import os
import re
import sys
import time
import uuid
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

SQLITE_DB_PATHS = [
    PROJECT_ROOT / "data" / "operations.db",
    Path("C:/var/data/operations.db"),
]

SYSTEM_DOMAINS = {
    "wingedtycoons.com", "microsoft.com", "render.com", "github.com",
    "postman.com", "google.com", "aftership.com", "twilio.com", "sendgrid.net",
    "azure.com", "office365.com", "protection.outlook.com"
}

def clean_client_name(name: str, domain: str) -> str:
    clean = re.sub(r'[\r\n\t]+', ' ', name or '').strip()
    clean = re.sub(r'(?i)\b(sales|purchasing|quotes|rfq|orders|info|support|buyer|procurement|logistics|team|dept|parts)\b', '', clean).strip()
    clean = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', clean).strip()
    if not clean or len(clean) < 2:
        parts = domain.split('.')[0].replace('-', ' ').replace('_', ' ')
        clean = parts.title()
    return clean

def get_graph_token():
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

def sync_clients(max_pages_per_folder: int = 200):
    print("=" * 70, flush=True)
    print("WINGED TYCOONS - CLIENT CONSOLIDATION & MAILBOX INGESTION SYNC", flush=True)
    print("=" * 70, flush=True)

    discovered_clients = {}  # domain -> {email: {name, last_contact, source}}

    # 1. Harvest from local operations.db historical records
    print("Harvesting existing client records from operations.db...", flush=True)
    for db_path in SQLITE_DB_PATHS:
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

            # From customers table
            if "customers" in tables:
                rows = cur.execute("SELECT email, company_name, contact_name, created_at FROM customers WHERE email IS NOT NULL AND email != ''").fetchall()
                for r in rows:
                    em = r["email"].strip().lower()
                    if "@" in em:
                        d = em.split("@")[1].strip().lower()
                        if d not in SYSTEM_DOMAINS:
                            discovered_clients.setdefault(d, {})[em] = {
                                "name": r["contact_name"] or r["company_name"] or "",
                                "last_contact": r["created_at"],
                                "source": "customers_table"
                            }

            # From client_quote_history table
            if "client_quote_history" in tables:
                rows = cur.execute("SELECT DISTINCT client_email, client_name, company_name, sent_at FROM client_quote_history WHERE client_email IS NOT NULL AND client_email != ''").fetchall()
                for r in rows:
                    em = r["client_email"].strip().lower()
                    if "@" in em:
                        d = em.split("@")[1].strip().lower()
                        if d not in SYSTEM_DOMAINS:
                            if d not in discovered_clients or em not in discovered_clients[d]:
                                discovered_clients.setdefault(d, {})[em] = {
                                    "name": r["client_name"] or r["company_name"] or "",
                                    "last_contact": r["sent_at"],
                                    "source": "client_quote_history"
                                }

            # From communications table
            if "communications" in tables:
                rows = cur.execute("SELECT DISTINCT recipient, subject, sent_at FROM communications WHERE recipient IS NOT NULL AND recipient != ''").fetchall()
                for r in rows:
                    em = r["recipient"].strip().lower()
                    if "@" in em:
                        d = em.split("@")[1].strip().lower()
                        if d not in SYSTEM_DOMAINS:
                            if d not in discovered_clients or em not in discovered_clients[d]:
                                discovered_clients.setdefault(d, {})[em] = {
                                    "name": "",
                                    "last_contact": r["sent_at"],
                                    "source": "communications"
                                }

            conn.close()
        except Exception as e:
            print(f"  Error reading {db_path}: {e}", flush=True)

    print(f"Base historical client pool: {len(discovered_clients)} unique client domains discovered.", flush=True)

    # 2. Ingest live from Microsoft Graph mailboxes
    token = get_graph_token()
    headers = {"Authorization": f"Bearer {token}"}
    mailboxes = [
        ("sales@wingedtycoons.com", ["sentitems", "inbox"]),
        ("rfq@wingedtycoons.com", ["inbox", "sentitems"]),
        ("quotes@wingedtycoons.com", ["inbox", "sentitems"]),
    ]

    total_messages_scanned = 0
    start_time = time.time()

    for mailbox, folders in mailboxes:
        print(f"\nProcessing mailbox {mailbox}...", flush=True)
        for folder_name in folders:
            print(f"  Scanning {folder_name} folder in {mailbox}...", flush=True)
            url = f"https://graph.microsoft.com/v1.0/users/{mailbox}/mailFolders/{folder_name}/messages?$top=50&$select=from,sender,toRecipients,receivedDateTime,subject"
            pages = 0
            folder_msgs = 0

            while url and pages < max_pages_per_folder:
                try:
                    resp = requests.get(url, headers=headers, timeout=20)
                    if resp.status_code == 401:
                        token = get_graph_token()
                        headers = {"Authorization": f"Bearer {token}"}
                        resp = requests.get(url, headers=headers, timeout=20)
                    if resp.status_code != 200:
                        print(f"    Warning: Graph returned {resp.status_code}, moving to next folder.", flush=True)
                        break
                    data = resp.json()
                    items = data.get("value", [])
                    if not items:
                        break

                    folder_msgs += len(items)
                    total_messages_scanned += len(items)
                    pages += 1

                    for it in items:
                        dt = it.get("receivedDateTime")
                        candidates = []
                        f = (it.get("from") or it.get("sender") or {}).get("emailAddress", {})
                        if f:
                            candidates.append(f)
                        for rec in it.get("toRecipients") or []:
                            candidates.append(rec.get("emailAddress", {}))

                        for c in candidates:
                            addr = c.get("address", "").strip().lower()
                            name = c.get("name", "").strip()
                            if addr and "@" in addr:
                                domain = addr.split("@")[1].strip().lower()
                                if domain not in SYSTEM_DOMAINS:
                                    if domain not in discovered_clients:
                                        discovered_clients[domain] = {}
                                    if addr not in discovered_clients[domain]:
                                        discovered_clients[domain][addr] = {
                                            "name": name,
                                            "email": addr,
                                            "last_contact": dt,
                                            "source": f"{mailbox}/{folder_name}",
                                        }
                                    else:
                                        if dt and (not discovered_clients[domain][addr]["last_contact"] or dt > discovered_clients[domain][addr]["last_contact"]):
                                            discovered_clients[domain][addr]["last_contact"] = dt
                                            if name and not discovered_clients[domain][addr]["name"]:
                                                discovered_clients[domain][addr]["name"] = name

                    url = data.get("@odata.nextLink")
                    if pages % 10 == 0:
                        print(f"    [{mailbox}/{folder_name}] Scanned {folder_msgs} msgs | Total client domains so far: {len(discovered_clients)}", flush=True)
                except Exception as e:
                    print(f"    Error reading page in {mailbox}/{folder_name}: {e}", flush=True)
                    break

            print(f"  Finished {mailbox}/{folder_name}: {folder_msgs} messages scanned. Current client domains: {len(discovered_clients)}", flush=True)

    elapsed = time.time() - start_time
    total_client_contacts = sum(len(c) for c in discovered_clients.values())
    print("\n" + "=" * 70, flush=True)
    print(f"CLIENT INGESTION COMPLETE: {total_messages_scanned} emails scanned in {elapsed:.1f}s", flush=True)
    print(f"Found {len(discovered_clients)} UNIQUE CLIENT DOMAINS with {total_client_contacts} individual contacts.", flush=True)
    print("=" * 70, flush=True)

    # Persist into operations.db
    now_iso = datetime.now(timezone.utc).isoformat()
    for db_path in SQLITE_DB_PATHS:
        if not db_path.exists() and not db_path.parent.exists():
            continue
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS customers (
                    id TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    contact_name TEXT,
                    email TEXT UNIQUE,
                    phone TEXT,
                    country TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

            inserted = 0
            updated = 0
            for domain, contacts in discovered_clients.items():
                for email, info in contacts.items():
                    comp_name = clean_client_name(info["name"], domain)
                    contact_name = info["name"] or comp_name
                    cur.execute("SELECT id FROM customers WHERE email = ?", (email,))
                    row = cur.fetchone()
                    if row:
                        cur.execute("UPDATE customers SET updated_at = ? WHERE id = ?", (now_iso, row["id"]))
                        updated += 1
                    else:
                        cust_id = f"CUST-{uuid.uuid4().hex[:8].upper()}"
                        cur.execute(
                            "INSERT INTO customers (id, company_name, contact_name, email, phone, country, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, NULL, 'USA', ?, ?)",
                            (cust_id, comp_name, contact_name, email, now_iso, now_iso)
                        )
                        inserted += 1

            conn.commit()
            cur.execute("SELECT count(*) FROM customers")
            total_customers = cur.fetchone()[0]
            conn.close()
            print(f"Persisted to {db_path}: +{inserted} new customers, {updated} updated (Total in DB: {total_customers})", flush=True)
        except Exception as e:
            print(f"Error persisting to {db_path}: {e}", flush=True)

    return discovered_clients

if __name__ == "__main__":
    sync_clients()
