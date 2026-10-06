"""High-speed synchronization of all supplier contacts from purchasing@wingedtycoons.com via Microsoft Graph."""

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
    PROJECT_ROOT / "data" / "supplier_email_store.db",
    PROJECT_ROOT / "data" / "operations.db",
    Path("C:/var/data/supplier_email_store.db"),
    Path("C:/var/data/operations.db"),
]

SYSTEM_DOMAINS = {
    "wingedtycoons.com", "microsoft.com", "render.com", "github.com",
    "postman.com", "google.com", "aftership.com", "twilio.com", "sendgrid.net",
    "azure.com", "office365.com", "protection.outlook.com"
}

def clean_company_name(name: str, domain: str) -> str:
    clean = re.sub(r'[\r\n\t]+', ' ', name or '').strip()
    clean = re.sub(r'(?i)\b(sales|purchasing|quotes|rfq|orders|info|support|team|dept|department|parts|aviation|aero)\b', '', clean).strip()
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

def sync_suppliers(max_pages_per_folder: int = 500):
    print("=" * 70, flush=True)
    print("WINGED TYCOONS - SUPPLIER MAILBOX FULL INGESTION SYNC", flush=True)
    print("=" * 70, flush=True)

    token = get_graph_token()
    headers = {"Authorization": f"Bearer {token}"}
    mailbox = "purchasing@wingedtycoons.com"

    # Discover all folders in purchasing mailbox
    print(f"Querying mail folders for {mailbox}...", flush=True)
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

    # Priority order
    priority = [
        "Inbox/Choosen Suppliers",
        "Inbox/Best Price",
        "Inbox/Fast Sales - List",
        "Inbox/Better Condition",
        "Inbox",
        "Sent Items",
        "Archive",
        "Deleted Items",
    ]

    folders_to_scan = []
    for p in priority:
        if p in folder_map:
            folders_to_scan.append((folder_map[p][0], p, folder_map[p][1]))
    for fname, (fid, cnt) in folder_map.items():
        if fname not in priority:
            folders_to_scan.append((fid, fname, cnt))

    print(f"Ordered {len(folders_to_scan)} folders for priority ingestion:", flush=True)
    for _, fname, cnt in folders_to_scan:
        print(f"  - {fname}: {cnt} items", flush=True)

    discovered_suppliers = {}  # domain -> {email: {name, last_contact, subject}}
    total_messages_scanned = 0
    start_time = time.time()

    for fid, fname, expected_cnt in folders_to_scan:
        print(f"\nScanning folder '{fname}' ({expected_cnt} items)...", flush=True)
        url = f"https://graph.microsoft.com/v1.0/users/{mailbox}/mailFolders/{fid}/messages?$top=50&$select=from,sender,toRecipients,receivedDateTime,subject"
        folder_msgs = 0
        pages = 0

        while url and pages < max_pages_per_folder:
            try:
                resp = requests.get(url, headers=headers, timeout=20)
                if resp.status_code == 401:
                    token = get_graph_token()
                    headers = {"Authorization": f"Bearer {token}"}
                    resp = requests.get(url, headers=headers, timeout=20)
                if resp.status_code != 200:
                    print(f"  Warning: Graph returned {resp.status_code} on {fname}, moving on.", flush=True)
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
                    subj = it.get("subject", "")
                    
                    # Gather both from/sender and toRecipients
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
                                if domain not in discovered_suppliers:
                                    discovered_suppliers[domain] = {}
                                if addr not in discovered_suppliers[domain]:
                                    discovered_suppliers[domain][addr] = {
                                        "name": name,
                                        "email": addr,
                                        "last_contact": dt,
                                        "sample_subject": subj,
                                    }
                                else:
                                    if dt and (not discovered_suppliers[domain][addr]["last_contact"] or dt > discovered_suppliers[domain][addr]["last_contact"]):
                                        discovered_suppliers[domain][addr]["last_contact"] = dt
                                        if name and not discovered_suppliers[domain][addr]["name"]:
                                            discovered_suppliers[domain][addr]["name"] = name

                url = data.get("@odata.nextLink")
                if pages % 5 == 0:
                    print(f"  [{fname}] Scanned {folder_msgs}/{expected_cnt} msgs | Total unique supplier domains so far: {len(discovered_suppliers)}", flush=True)
            except Exception as e:
                print(f"  Error reading page in {fname}: {e}", flush=True)
                break

        print(f"Completed folder '{fname}': scanned {folder_msgs} messages. Total domains: {len(discovered_suppliers)}", flush=True)

    elapsed = time.time() - start_time
    total_contacts = sum(len(c) for c in discovered_suppliers.values())
    print("\n" + "=" * 70, flush=True)
    print(f"SUPPLIER INGESTION COMPLETE: {total_messages_scanned} emails scanned in {elapsed:.1f}s", flush=True)
    print(f"Found {len(discovered_suppliers)} UNIQUE SUPPLIER DOMAINS with {total_contacts} individual contacts.", flush=True)
    print("=" * 70, flush=True)

    # Persist all discovered suppliers into SQLite databases
    now_iso = datetime.now(timezone.utc).isoformat()
    for db_path in SQLITE_DB_PATHS:
        if not db_path.exists() and not db_path.parent.exists():
            continue
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            cur.execute("PRAGMA table_info(suppliers)")
            existing_cols = {r[1] for r in cur.fetchall()}
            if not existing_cols:
                cur.execute("""
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
                """)
                cur.execute("PRAGMA table_info(suppliers)")
                existing_cols = {r[1] for r in cur.fetchall()}

            inserted = 0
            updated = 0
            for domain, contacts in discovered_suppliers.items():
                for email, info in contacts.items():
                    comp_name = clean_company_name(info["name"], domain)
                    cur.execute("SELECT id FROM suppliers WHERE email = ?", (email,))
                    row = cur.fetchone()
                    if row:
                        if "approval_status" in existing_cols:
                            cur.execute(
                                "UPDATE suppliers SET updated_at = ?, approval_status = 'Approved' WHERE id = ?",
                                (now_iso, row["id"])
                            )
                        else:
                            cur.execute(
                                "UPDATE suppliers SET updated_at = ?, active = 1 WHERE id = ?",
                                (now_iso, row["id"])
                            )
                        updated += 1
                    else:
                        sup_id = f"SUP-{uuid.uuid4().hex[:8].upper()}"
                        if "approval_status" in existing_cols:
                            cur.execute(
                                "INSERT INTO suppliers (id, company_name, email, phone, approval_status, itar_certified, source, created_at, updated_at) "
                                "VALUES (?, ?, ?, NULL, 'Approved', 0, 'purchasing_mailbox_sync', ?, ?)",
                                (sup_id, comp_name, email, now_iso, now_iso)
                            )
                        else:
                            cur.execute(
                                "INSERT INTO suppliers (id, company_name, contact_name, email, phone, country, preferred, active, created_at, updated_at) "
                                "VALUES (?, ?, ?, ?, NULL, 'USA', 0, 1, ?, ?)",
                                (sup_id, comp_name, comp_name, email, now_iso, now_iso)
                            )
                        inserted += 1

            conn.commit()
            cur.execute("SELECT count(DISTINCT email) FROM suppliers")
            total_suppliers = cur.fetchone()[0]
            conn.close()
            print(f"Persisted to {db_path}: +{inserted} new contacts, {updated} updated (Total distinct suppliers: {total_suppliers})", flush=True)
        except Exception as e:
            print(f"Error persisting to {db_path}: {e}", flush=True)

    return discovered_suppliers

if __name__ == "__main__":
    sync_suppliers()
