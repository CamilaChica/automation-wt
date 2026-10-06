"""Email Campaign Engine for Winged Tycoons.

Manages three specific campaigns:
1. Supplier Outreach Campaign (Immediate, unique domain enforcement with fallback on failure).
2. Client Portal Launch Campaign (Scheduled for next week).
3. User Feedback Campaign (Scheduled 1 hour after first-time portal login only).
"""

import os
import re
import sqlite3
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Any, Dict, Iterator, List, Optional, Tuple

from services.mailbox_service import html_to_text, send_message

OPERATIONS_DB_PATH = os.getenv("OPERATIONS_DB_PATH", "data/operations.db")
SUPPLIER_DB_PATH = os.getenv("SUPPLIER_DB_PATH", "data/supplier_email_store.db")
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

SUPPLIER_TEMPLATE_PATH = os.path.join(
    BASE_DIR, "email_campaigns", "suppliers-email-campaign", "email-campaign-suppliers.html"
)
CLIENT_PORTAL_TEMPLATE_PATH = os.path.join(
    BASE_DIR, "email_campaigns", "clients-email-campaign", "email-campaign-portal.html"
)
USER_FEEDBACK_TEMPLATE_PATH = os.path.join(
    BASE_DIR, "email_campaigns", "clients-email-campaign", "email-feedback-form.html"
)

CAMPAIGN_SUPPLIERS = "suppliers-circle"
CAMPAIGN_CLIENTS = "clients-portal-launch"
CAMPAIGN_USER_FEEDBACK = "user-feedback-first-login"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_next_week_start(now: Optional[datetime] = None) -> datetime:
    """Calculate the starting timestamp for next week (next Monday at 09:00 UTC)."""
    if now is None:
        now = datetime.now(timezone.utc)
    # Days until next Monday (0 = Monday, 6 = Sunday)
    days_ahead = 7 - now.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    next_monday = (now + timedelta(days=days_ahead)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    return next_monday


def extract_domain(email_address: str) -> str:
    """Extract and normalize the domain from an email address."""
    clean = parseaddr(email_address.strip().lower())[1]
    if "@" in clean:
        return clean.split("@")[-1].strip().lower()
    return ""


def extract_first_name(full_name: str, email_address: str = "") -> str:
    """Derive a friendly first name from name or email address."""
    name_clean = full_name.strip()
    if name_clean and not name_clean.startswith("http") and not "@" in name_clean:
        # Avoid generic titles like "Mr.", "Ms.", "Dr."
        tokens = [t for t in name_clean.split() if t.lower() not in {"mr.", "ms.", "mrs.", "dr.", "team"}]
        if tokens:
            return tokens[0].capitalize()
    if email_address and "@" in email_address:
        prefix = email_address.split("@")[0]
        # if email prefix is firstname.lastname or similar
        first_token = re.split(r"[._-]", prefix)[0]
        if first_token.isalpha() and len(first_token) >= 2 and first_token.lower() not in {"sales", "procurement", "quotes", "info", "contact", "support", "orders", "parts"}:
            return first_token.capitalize()
    return "there"


class EmailCampaignService:
    def __init__(self, db_path: str = OPERATIONS_DB_PATH, supplier_db_path: str = SUPPLIER_DB_PATH):
        self.db_path = db_path
        self.supplier_db_path = supplier_db_path
        self._ensure_schema()

    @contextmanager
    def _connect_ops(self) -> Iterator[sqlite3.Connection]:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _connect_suppliers(self) -> Iterator[sqlite3.Connection]:
        os.makedirs(os.path.dirname(self.supplier_db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self.supplier_db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        """Create campaign tables in the operations database if they do not exist."""
        with self._connect_ops() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS email_campaigns (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    target_audience TEXT NOT NULL,
                    template_path TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    from_mailbox TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    schedule_type TEXT NOT NULL,
                    scheduled_start_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS email_campaign_dispatches (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES email_campaigns(id),
                    recipient_email TEXT NOT NULL,
                    recipient_name TEXT,
                    company_name TEXT,
                    domain TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    scheduled_for TEXT NOT NULL,
                    sent_at TEXT,
                    error_message TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    fallback_contacts TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_ecd_campaign_status ON email_campaign_dispatches(campaign_id, status);
                CREATE INDEX IF NOT EXISTS idx_ecd_domain ON email_campaign_dispatches(campaign_id, domain);
                CREATE INDEX IF NOT EXISTS idx_ecd_recipient ON email_campaign_dispatches(campaign_id, recipient_email);
                CREATE INDEX IF NOT EXISTS idx_ecd_scheduled_for ON email_campaign_dispatches(status, scheduled_for);
                """
            )
            # Add fallback_contacts column if older schema
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(email_campaign_dispatches)").fetchall()}
            if "fallback_contacts" not in columns:
                conn.execute("ALTER TABLE email_campaign_dispatches ADD COLUMN fallback_contacts TEXT")

            # Seed default campaigns if missing
            self._seed_default_campaigns(conn)

    def _seed_default_campaigns(self, conn: sqlite3.Connection) -> None:
        now = _now_iso()
        next_week = get_next_week_start().isoformat()

        default_campaigns = [
            (
                CAMPAIGN_SUPPLIERS,
                "Preferred Supplier Circle Outreach",
                "suppliers",
                SUPPLIER_TEMPLATE_PATH,
                "You're invited: Winged Tycoons Preferred Supplier Circle",
                "purchasing",
                "ACTIVE",
                "immediate",
                now,
                now,
                now,
            ),
            (
                CAMPAIGN_CLIENTS,
                "24/7 Parts Sourcing Client Portal Launch",
                "clients",
                CLIENT_PORTAL_TEMPLATE_PATH,
                "Source your aircraft parts 24/7 - Winged Tycoons",
                "sales",
                "SCHEDULED",
                "scheduled_date",
                next_week,
                now,
                now,
            ),
            (
                CAMPAIGN_USER_FEEDBACK,
                "New User First-Login Portal Feedback",
                "users",
                USER_FEEDBACK_TEMPLATE_PATH,
                "We'd love your feedback - Winged Tycoons",
                "sales",
                "ACTIVE",
                "event_triggered",
                None,
                now,
                now,
            ),
        ]

        for camp in default_campaigns:
            conn.execute(
                """
                INSERT INTO email_campaigns (
                    id, name, target_audience, template_path, subject, from_mailbox,
                    status, schedule_type, scheduled_start_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    template_path = excluded.template_path,
                    subject = excluded.subject,
                    from_mailbox = excluded.from_mailbox,
                    updated_at = excluded.updated_at
                """,
                camp,
            )

    def render_template(
        self,
        template_path: str,
        first_name: str = "",
        company_name: str = "",
        recipient_email: str = "",
    ) -> str:
        """Render campaign HTML template with variable replacement."""
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Campaign template not found at {template_path}")

        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()

        clean_first_name = first_name.strip() if first_name else "there"
        clean_company = company_name.strip() if company_name else "your team"
        unsubscribe_url = (
            f"https://portal.wingedtycoons.com/unsubscribe?email={urllib.parse.quote(recipient_email)}"
        )

        html = html.replace("{{first_name}}", clean_first_name)
        html = html.replace("{{company_name}}", clean_company)
        html = html.replace("{{unsubscribe_url}}", unsubscribe_url)
        return html

    # -------------------------------------------------------------------------
    # Campaign 1: Supplier Outreach (Domain Deduplication & Fallback)
    # -------------------------------------------------------------------------
    def prepare_supplier_campaign(self) -> Dict[str, Any]:
        """
        Populate the supplier campaign dispatches.
        Rule: Do not repeat domain. If multiple contacts exist on a domain,
        pick the primary contact and retain the others as fallbacks if the primary fails.
        """
        now = _now_iso()
        contacts_by_domain: Dict[str, List[Dict[str, str]]] = {}

        # 1. Fetch from supplier_email_store
        try:
            with self._connect_suppliers() as sconn:
                rows = sconn.execute(
                    "SELECT company_name, email FROM suppliers WHERE email IS NOT NULL AND email != ''"
                ).fetchall()
                for r in rows:
                    em = r["email"].strip().lower()
                    dom = extract_domain(em)
                    if dom:
                        contacts_by_domain.setdefault(dom, []).append(
                            {"company_name": r["company_name"] or "", "email": em}
                        )
        except Exception:
            pass

        # 2. Fetch from operations inventory imports or suppliers table
        try:
            with self._connect_ops() as oconn:
                tables = {row["name"] for row in oconn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                if "suppliers" in tables:
                    rows = oconn.execute(
                        "SELECT company_name, email FROM suppliers WHERE email IS NOT NULL AND email != ''"
                    ).fetchall()
                    for r in rows:
                        em = r["email"].strip().lower()
                        dom = extract_domain(em)
                        if dom:
                            contacts_by_domain.setdefault(dom, []).append(
                                {"company_name": r["company_name"] or "", "email": em}
                            )
        except Exception:
            pass

        dispatches_created = 0
        with self._connect_ops() as conn:
            for domain, contacts in contacts_by_domain.items():
                # Check if a dispatch for this domain already exists in this campaign
                existing = conn.execute(
                    "SELECT id, status, recipient_email FROM email_campaign_dispatches WHERE campaign_id = ? AND domain = ?",
                    (CAMPAIGN_SUPPLIERS, domain),
                ).fetchone()

                if existing:
                    continue

                primary = contacts[0]
                first_name = extract_first_name("", primary["email"])
                company = primary["company_name"] or domain.split(".")[0].capitalize()
                fallback_list = [c["email"] for c in contacts[1:] if c["email"] != primary["email"]]
                fallback_json = ",".join(fallback_list) if fallback_list else None

                dispatch_id = f"disp-sup-{domain.replace('.', '_')}"
                conn.execute(
                    """
                    INSERT INTO email_campaign_dispatches (
                        id, campaign_id, recipient_email, recipient_name, company_name,
                        domain, status, scheduled_for, fallback_contacts, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)
                    """,
                    (
                        dispatch_id,
                        CAMPAIGN_SUPPLIERS,
                        primary["email"],
                        first_name,
                        company,
                        domain,
                        now,
                        fallback_json,
                        now,
                        now,
                    ),
                )
                dispatches_created += 1

        return {
            "campaign_id": CAMPAIGN_SUPPLIERS,
            "unique_domains": len(contacts_by_domain),
            "dispatches_created": dispatches_created,
            "status": "ready_effective_immediately",
        }

    # -------------------------------------------------------------------------
    # Campaign 2: Clients Outreach (Starting Next Week)
    # -------------------------------------------------------------------------
    def prepare_client_campaign(self, scheduled_start: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Populate the client campaign dispatches.
        Rule: Starting next week. Deduplicate by client email.
        """
        now = _now_iso()
        start_time = scheduled_start or get_next_week_start()
        scheduled_for_iso = start_time.isoformat()

        client_map: Dict[str, Dict[str, str]] = {}

        # 1. Fetch from client quote history
        with self._connect_ops() as conn:
            tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "client_quote_history" in tables:
                rows = conn.execute(
                    "SELECT DISTINCT client_email, client_name, company_name FROM client_quote_history WHERE client_email IS NOT NULL AND client_email != ''"
                ).fetchall()
                for r in rows:
                    em = r["client_email"].strip().lower()
                    if em:
                        client_map[em] = {
                            "name": r["client_name"] or "",
                            "company": r["company_name"] or "",
                        }

            # 2. Fetch from customers table
            if "customers" in tables:
                rows = conn.execute(
                    "SELECT email, contact_name, company_name FROM customers WHERE email IS NOT NULL AND email != ''"
                ).fetchall()
                for r in rows:
                    em = r["email"].strip().lower()
                    if em and em not in client_map:
                        client_map[em] = {
                            "name": r["contact_name"] or "",
                            "company": r["company_name"] or "",
                        }

            dispatches_created = 0
            for email, data in client_map.items():
                existing = conn.execute(
                    "SELECT id FROM email_campaign_dispatches WHERE campaign_id = ? AND recipient_email = ?",
                    (CAMPAIGN_CLIENTS, email),
                ).fetchone()

                if existing:
                    continue

                domain = extract_domain(email)
                first_name = extract_first_name(data["name"], email)
                company = data["company"] or (domain.split(".")[0].capitalize() if domain else "Your Team")

                dispatch_id = f"disp-cli-{hash(email) & 0xFFFFFFFF:08x}"
                conn.execute(
                    """
                    INSERT INTO email_campaign_dispatches (
                        id, campaign_id, recipient_email, recipient_name, company_name,
                        domain, status, scheduled_for, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'SCHEDULED', ?, ?, ?)
                    """,
                    (
                        dispatch_id,
                        CAMPAIGN_CLIENTS,
                        email,
                        first_name,
                        company,
                        domain,
                        scheduled_for_iso,
                        now,
                        now,
                    ),
                )
                dispatches_created += 1

            # Update campaign record with scheduled start
            conn.execute(
                "UPDATE email_campaigns SET scheduled_start_at = ?, status = 'SCHEDULED', updated_at = ? WHERE id = ?",
                (scheduled_for_iso, now, CAMPAIGN_CLIENTS),
            )

        return {
            "campaign_id": CAMPAIGN_CLIENTS,
            "total_clients": len(client_map),
            "dispatches_created": dispatches_created,
            "scheduled_start_at": scheduled_for_iso,
            "status": "scheduled_for_next_week",
        }

    # -------------------------------------------------------------------------
    # Campaign 3: User Post-Login Feedback (1 hour after first login only)
    # -------------------------------------------------------------------------
    def schedule_user_feedback(
        self,
        user_email: str,
        first_name: str = "",
        company_name: str = "",
        now: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Schedule feedback email for a user 1 hour after first login.
        Rule: For the first time only.
        """
        clean_email = user_email.strip().lower()
        if not clean_email or "@" not in clean_email:
            return None

        # Exclude internal staff from client feedback
        if clean_email.endswith("@wingedtycoons.com"):
            return None

        current_dt = now or datetime.now(timezone.utc)
        scheduled_for_dt = current_dt + timedelta(hours=1)
        now_iso = current_dt.isoformat()
        scheduled_for_iso = scheduled_for_dt.isoformat()

        with self._connect_ops() as conn:
            # Check if this user was already scheduled or sent for this campaign (First time only)
            existing = conn.execute(
                "SELECT id, status, scheduled_for FROM email_campaign_dispatches WHERE campaign_id = ? AND recipient_email = ?",
                (CAMPAIGN_USER_FEEDBACK, clean_email),
            ).fetchone()

            if existing:
                return {
                    "scheduled": False,
                    "reason": "already_scheduled_or_sent",
                    "dispatch_id": existing["id"],
                    "status": existing["status"],
                }

            domain = extract_domain(clean_email)
            name_derived = first_name or extract_first_name("", clean_email)
            company_derived = company_name or (domain.split(".")[0].capitalize() if domain else "Your Team")

            dispatch_id = f"disp-feed-{hash(clean_email) & 0xFFFFFFFF:08x}"
            conn.execute(
                """
                INSERT INTO email_campaign_dispatches (
                    id, campaign_id, recipient_email, recipient_name, company_name,
                    domain, status, scheduled_for, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'SCHEDULED', ?, ?, ?)
                """,
                (
                    dispatch_id,
                    CAMPAIGN_USER_FEEDBACK,
                    clean_email,
                    name_derived,
                    company_derived,
                    domain,
                    scheduled_for_iso,
                    now_iso,
                    now_iso,
                ),
            )

        return {
            "scheduled": True,
            "campaign_id": CAMPAIGN_USER_FEEDBACK,
            "dispatch_id": dispatch_id,
            "recipient_email": clean_email,
            "scheduled_for": scheduled_for_iso,
        }

    # -------------------------------------------------------------------------
    # Dispatch & Processing Engine
    # -------------------------------------------------------------------------
    def send_dispatch(self, dispatch_id: str) -> bool:
        """
        Send a specific campaign dispatch.
        Handles domain fallback for suppliers: if primary fails, tries fallback contact.
        """
        with self._connect_ops() as conn:
            dispatch = conn.execute(
                "SELECT d.*, c.template_path, c.subject, c.from_mailbox FROM email_campaign_dispatches d JOIN email_campaigns c ON c.id = d.campaign_id WHERE d.id = ?",
                (dispatch_id,),
            ).fetchone()

            if not dispatch:
                return False

            if dispatch["status"] == "SENT":
                return True

            campaign_id = dispatch["campaign_id"]
            recipient = dispatch["recipient_email"]
            name = dispatch["recipient_name"] or ""
            company = dispatch["company_name"] or ""
            mailbox = dispatch["from_mailbox"]
            subject = dispatch["subject"]
            template_path = dispatch["template_path"]
            fallback_contacts = (dispatch["fallback_contacts"] or "").split(",") if dispatch["fallback_contacts"] else []

            # Render HTML and plain text
            html_content = self.render_template(
                template_path=template_path,
                first_name=name,
                company_name=company,
                recipient_email=recipient,
            )
            text_content = html_to_text(html_content)

            try:
                send_message(
                    mailbox=mailbox,
                    recipient=recipient,
                    subject=subject,
                    body=text_content,
                    html_body=html_content,
                )

                now_iso = _now_iso()
                conn.execute(
                    "UPDATE email_campaign_dispatches SET status = 'SENT', sent_at = ?, attempts = attempts + 1, updated_at = ? WHERE id = ?",
                    (now_iso, now_iso, dispatch_id),
                )
                return True

            except Exception as exc:
                error_msg = str(exc)
                attempts = dispatch["attempts"] + 1
                now_iso = _now_iso()

                # Supplier campaign fallback handling: If current email fails/bounced, try next contact on that domain
                if campaign_id == CAMPAIGN_SUPPLIERS and fallback_contacts:
                    next_contact = fallback_contacts[0].strip()
                    remaining_fallbacks = ",".join(fallback_contacts[1:]) if len(fallback_contacts) > 1 else None

                    # Mark current as failed
                    conn.execute(
                        "UPDATE email_campaign_dispatches SET status = 'FAILED', error_message = ?, attempts = ?, updated_at = ? WHERE id = ?",
                        (f"Failed ({error_msg}); falling back to {next_contact}", attempts, now_iso, dispatch_id),
                    )

                    # Create fallback dispatch for the domain
                    fallback_id = f"disp-sup-{dispatch['domain'].replace('.', '_')}-fallback"
                    conn.execute(
                        """
                        INSERT INTO email_campaign_dispatches (
                            id, campaign_id, recipient_email, recipient_name, company_name,
                            domain, status, scheduled_for, fallback_contacts, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET recipient_email = excluded.recipient_email, status = 'PENDING'
                        """,
                        (
                            fallback_id,
                            CAMPAIGN_SUPPLIERS,
                            next_contact,
                            name,
                            company,
                            dispatch["domain"],
                            now_iso,
                            remaining_fallbacks,
                            now_iso,
                            now_iso,
                        ),
                    )
                else:
                    conn.execute(
                        "UPDATE email_campaign_dispatches SET status = 'FAILED', error_message = ?, attempts = ?, updated_at = ? WHERE id = ?",
                        (error_msg, attempts, now_iso, dispatch_id),
                    )

                return False

    def process_due_dispatches(self, campaign_id: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """
        Process any dispatches whose scheduled_for timestamp has arrived.
        """
        now_iso = _now_iso()
        processed = 0
        successes = 0
        failures = 0

        with self._connect_ops() as conn:
            query = """
                SELECT id FROM email_campaign_dispatches
                WHERE status IN ('PENDING', 'SCHEDULED')
                  AND scheduled_for <= ?
            """
            params: List[Any] = [now_iso]
            if campaign_id:
                query += " AND campaign_id = ?"
                params.append(campaign_id)
            query += " ORDER BY scheduled_for ASC LIMIT ?"
            params.append(limit)

            due_rows = conn.execute(query, params).fetchall()

        for row in due_rows:
            processed += 1
            if self.send_dispatch(row["id"]):
                successes += 1
            else:
                failures += 1

        return {
            "processed": processed,
            "successes": successes,
            "failures": failures,
            "timestamp": now_iso,
        }

    def run_supplier_campaign_now(self) -> Dict[str, Any]:
        """
        Run the supplier campaign immediately:
        1. Prepare unique domain dispatches.
        2. Process all pending dispatches immediately.
        """
        prep_result = self.prepare_supplier_campaign()
        process_result = self.process_due_dispatches(campaign_id=CAMPAIGN_SUPPLIERS, limit=100)
        return {
            "preparation": prep_result,
            "execution": process_result,
        }

    def get_campaign_summaries(self) -> List[Dict[str, Any]]:
        """Return status, counts, and schedules for all 3 campaigns."""
        summaries = []
        with self._connect_ops() as conn:
            campaigns = conn.execute("SELECT * FROM email_campaigns ORDER BY created_at ASC").fetchall()
            for c in campaigns:
                counts = conn.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'SENT' THEN 1 ELSE 0 END) as sent,
                        SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending,
                        SUM(CASE WHEN status = 'SCHEDULED' THEN 1 ELSE 0 END) as scheduled,
                        SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed
                    FROM email_campaign_dispatches
                    WHERE campaign_id = ?
                    """,
                    (c["id"],),
                ).fetchone()

                summaries.append({
                    "id": c["id"],
                    "name": c["name"],
                    "target_audience": c["target_audience"],
                    "status": c["status"],
                    "schedule_type": c["schedule_type"],
                    "scheduled_start_at": c["scheduled_start_at"],
                    "subject": c["subject"],
                    "from_mailbox": c["from_mailbox"],
                    "template_path": c["template_path"],
                    "metrics": {
                        "total": counts["total"] or 0,
                        "sent": counts["sent"] or 0,
                        "pending": counts["pending"] or 0,
                        "scheduled": counts["scheduled"] or 0,
                        "failed": counts["failed"] or 0,
                    },
                })
        return summaries


email_campaign_service = EmailCampaignService()
