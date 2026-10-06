"""Client Quote History Service.

Gathers, indexes, and provides query interfaces for all historical and active quotations
sent to clients. Tracks every part ever quoted to each customer, along with all details
sent to them (quote number, date, part number, description, condition, certification,
quantity, unit price, total price, lead time, validity, status, and full email body).
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from services.operations_store import operations_store

logger = logging.getLogger("winged-tycoons-client-history")


def _norm_pn(val: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(val or "").upper())


class ClientHistoryService:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self._init_tables()

    def _get_connection(self):
        if self.db_path:
            import sqlite3
            return sqlite3.connect(self.db_path)
        return operations_store._connect()

    def _init_tables(self) -> None:
        """Create client_quote_history table in operations store if not exists."""
        if operations_store.storage_engine == "postgresql" and operations_store._postgres:
            try:
                from sqlalchemy import text
                with operations_store._postgres._engine.begin() as conn:
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS client_quote_history (
                            id VARCHAR(64) PRIMARY KEY,
                            client_email VARCHAR(255) NOT NULL,
                            client_name VARCHAR(255),
                            company_name VARCHAR(255),
                            quote_number VARCHAR(120) NOT NULL,
                            rfq_id VARCHAR(120),
                            part_number VARCHAR(120) NOT NULL,
                            normalized_part_number VARCHAR(120) NOT NULL,
                            description TEXT,
                            quantity INTEGER NOT NULL DEFAULT 1,
                            uom VARCHAR(32) NOT NULL DEFAULT 'EA',
                            unit_price NUMERIC(14, 2) NOT NULL DEFAULT 0.0,
                            total_price NUMERIC(14, 2) NOT NULL DEFAULT 0.0,
                            currency VARCHAR(16) NOT NULL DEFAULT 'USD',
                            condition VARCHAR(64),
                            certification VARCHAR(120),
                            lead_time VARCHAR(120),
                            valid_until VARCHAR(64),
                            status VARCHAR(64) NOT NULL DEFAULT 'Sent',
                            sent_at TIMESTAMP WITH TIME ZONE NOT NULL,
                            email_subject TEXT,
                            email_body TEXT,
                            attachments TEXT,
                            source_mailbox VARCHAR(64) NOT NULL DEFAULT 'sales',
                            source_message_id TEXT,
                            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                            UNIQUE (quote_number, normalized_part_number, client_email)
                        );
                        CREATE INDEX IF NOT EXISTS idx_cqh_client_email ON client_quote_history(client_email);
                        CREATE INDEX IF NOT EXISTS idx_cqh_part_number ON client_quote_history(part_number);
                        CREATE INDEX IF NOT EXISTS idx_cqh_norm_part ON client_quote_history(normalized_part_number);
                        CREATE INDEX IF NOT EXISTS idx_cqh_quote_number ON client_quote_history(quote_number);
                    """))
                return
            except Exception as exc:
                logger.warning("Postgres client_quote_history table init skipped: %s", exc)

        # SQLite fallback
        try:
            conn = self._get_connection()
            try:
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
                        uom TEXT NOT NULL DEFAULT 'EA',
                        unit_price REAL NOT NULL DEFAULT 0.0,
                        total_price REAL NOT NULL DEFAULT 0.0,
                        currency TEXT NOT NULL DEFAULT 'USD',
                        condition TEXT,
                        certification TEXT,
                        lead_time TEXT,
                        valid_until TEXT,
                        status TEXT NOT NULL DEFAULT 'Sent',
                        sent_at TEXT NOT NULL,
                        email_subject TEXT,
                        email_body TEXT,
                        attachments TEXT,
                        source_mailbox TEXT NOT NULL DEFAULT 'sales',
                        source_message_id TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE (quote_number, normalized_part_number, client_email)
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cqh_client_email ON client_quote_history(client_email);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cqh_part_number ON client_quote_history(part_number);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cqh_norm_part ON client_quote_history(normalized_part_number);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cqh_quote_number ON client_quote_history(quote_number);")
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("SQLite client_quote_history table init error: %s", exc)

    def record_client_quote(
        self,
        *,
        client_email: str,
        quote_number: str,
        part_number: str,
        unit_price: float,
        quantity: int = 1,
        total_price: Optional[float] = None,
        client_name: Optional[str] = None,
        company_name: Optional[str] = None,
        rfq_id: Optional[str] = None,
        description: Optional[str] = None,
        uom: str = "EA",
        currency: str = "USD",
        condition: Optional[str] = None,
        certification: Optional[str] = None,
        lead_time: Optional[str] = None,
        valid_until: Optional[str] = None,
        status: str = "Sent",
        sent_at: Optional[str] = None,
        email_subject: Optional[str] = None,
        email_body: Optional[str] = None,
        attachments: Optional[List[str]] = None,
        source_mailbox: str = "sales",
        source_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record or update an individual client quote item into historical records."""
        clean_email = str(client_email or "").strip().lower()
        if not clean_email or "@" not in clean_email:
            raise ValueError(f"Valid client email is required: {client_email}")

        clean_pn = str(part_number or "").strip()
        if not clean_pn:
            raise ValueError("Part number is required to record client quote history")

        norm_pn = _norm_pn(clean_pn)
        qty = max(1, int(quantity or 1))
        u_price = float(unit_price or 0.0)
        t_price = float(total_price) if total_price is not None else (u_price * qty)

        now = datetime.now(timezone.utc).isoformat()
        quote_sent_at = str(sent_at or now)
        quote_id = f"CQH-{uuid.uuid4().hex[:16].upper()}"

        record = {
            "id": quote_id,
            "client_email": clean_email,
            "client_name": client_name or clean_email.split("@")[0].replace(".", " ").title(),
            "company_name": company_name or clean_email.split("@")[1].split(".")[0].upper(),
            "quote_number": str(quote_number or "").strip(),
            "rfq_id": str(rfq_id or ""),
            "part_number": clean_pn,
            "normalized_part_number": norm_pn,
            "description": str(description or clean_pn),
            "quantity": qty,
            "uom": str(uom or "EA"),
            "unit_price": u_price,
            "total_price": t_price,
            "currency": str(currency or "USD"),
            "condition": str(condition or "NE"),
            "certification": str(certification or "FAA 8130-3 / OEM CoC"),
            "lead_time": str(lead_time or "Stock"),
            "valid_until": str(valid_until or ""),
            "status": str(status or "Sent"),
            "sent_at": quote_sent_at,
            "email_subject": str(email_subject or ""),
            "email_body": str(email_body or ""),
            "attachments": json.dumps(attachments or []),
            "source_mailbox": str(source_mailbox or "sales"),
            "source_message_id": str(source_message_id or ""),
            "created_at": now,
            "updated_at": now,
        }

        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO client_quote_history (
                    id, client_email, client_name, company_name, quote_number, rfq_id,
                    part_number, normalized_part_number, description, quantity, uom,
                    unit_price, total_price, currency, condition, certification,
                    lead_time, valid_until, status, sent_at, email_subject, email_body,
                    attachments, source_mailbox, source_message_id, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
                ON CONFLICT(quote_number, normalized_part_number, client_email) DO UPDATE SET
                    client_name=COALESCE(excluded.client_name, client_quote_history.client_name),
                    company_name=COALESCE(excluded.company_name, client_quote_history.company_name),
                    description=COALESCE(excluded.description, client_quote_history.description),
                    quantity=excluded.quantity,
                    unit_price=excluded.unit_price,
                    total_price=excluded.total_price,
                    condition=COALESCE(excluded.condition, client_quote_history.condition),
                    certification=COALESCE(excluded.certification, client_quote_history.certification),
                    lead_time=COALESCE(excluded.lead_time, client_quote_history.lead_time),
                    valid_until=COALESCE(excluded.valid_until, client_quote_history.valid_until),
                    status=excluded.status,
                    sent_at=excluded.sent_at,
                    email_subject=COALESCE(excluded.email_subject, client_quote_history.email_subject),
                    email_body=COALESCE(excluded.email_body, client_quote_history.email_body),
                    attachments=COALESCE(excluded.attachments, client_quote_history.attachments),
                    updated_at=excluded.updated_at
                """,
                (
                    record["id"], record["client_email"], record["client_name"], record["company_name"],
                    record["quote_number"], record["rfq_id"], record["part_number"], record["normalized_part_number"],
                    record["description"], record["quantity"], record["uom"], record["unit_price"],
                    record["total_price"], record["currency"], record["condition"], record["certification"],
                    record["lead_time"], record["valid_until"], record["status"], record["sent_at"],
                    record["email_subject"], record["email_body"], record["attachments"],
                    record["source_mailbox"], record["source_message_id"], record["created_at"], record["updated_at"],
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return record

    def backfill_from_existing_database(self, limit: int = 10000) -> int:
        """Scan existing customer_quotes, customer_quote_items, rfqs, and customers to populate client_quote_history."""
        conn = self._get_connection()
        conn.row_factory = None
        count = 0
        try:
            # First, check quotes with explicit line items
            query_items = """
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
                    cq.created_at AS sent_at,
                    cqi.attachments
                FROM customer_quotes cq
                JOIN rfqs r ON cq.rfq_id = r.id
                JOIN customers c ON r.customer_id = c.id
                JOIN customer_quote_items cqi ON cqi.quote_id = cq.id
                WHERE c.email IS NOT NULL AND cqi.part_number IS NOT NULL
                LIMIT ?
            """
            cursor = conn.cursor()
            cursor.execute(query_items, (limit,))
            rows = cursor.fetchall()
            for r in rows:
                try:
                    att = json.loads(r[16]) if r[16] else []
                except Exception:
                    att = []
                self.record_client_quote(
                    client_email=r[0],
                    client_name=r[1],
                    company_name=r[2],
                    quote_number=r[3],
                    rfq_id=r[4],
                    part_number=r[5],
                    description=r[6],
                    quantity=r[7],
                    unit_price=r[8],
                    total_price=r[9],
                    condition=r[10],
                    certification=r[11],
                    lead_time=str(r[12]) if r[12] is not None else "Stock",
                    valid_until=r[13],
                    status=r[14],
                    sent_at=r[15],
                    attachments=att,
                )
                count += 1

            # Second, check quotes that may not have separate customer_quote_items but have part_number on rfq
            query_rfq_parts = """
                SELECT 
                    c.email AS client_email,
                    COALESCE(c.contact_name, c.company_name) AS client_name,
                    c.company_name,
                    cq.quote_number,
                    cq.rfq_id,
                    r.part_number,
                    r.description,
                    cq.quantity,
                    cq.unit_price,
                    cq.total_price,
                    cq.condition,
                    cq.certification,
                    cq.lead_time,
                    cq.valid_until,
                    cq.status,
                    cq.created_at AS sent_at
                FROM customer_quotes cq
                JOIN rfqs r ON cq.rfq_id = r.id
                JOIN customers c ON r.customer_id = c.id
                WHERE c.email IS NOT NULL AND r.part_number IS NOT NULL
                LIMIT ?
            """
            cursor.execute(query_rfq_parts, (limit,))
            for r in cursor.fetchall():
                try:
                    self.record_client_quote(
                        client_email=r[0],
                        client_name=r[1],
                        company_name=r[2],
                        quote_number=r[3],
                        rfq_id=r[4],
                        part_number=r[5],
                        description=r[6],
                        quantity=r[7],
                        unit_price=r[8],
                        total_price=r[9],
                        condition=r[10],
                        certification=r[11],
                        lead_time=str(r[12]) if r[12] is not None else "Stock",
                        valid_until=r[13],
                        status=r[14],
                        sent_at=r[15],
                    )
                    count += 1
                except Exception:
                    pass
        finally:
            conn.close()

        logger.info("backfilled_client_quote_history count=%d", count)
        return count

    def get_client_quote_history(self, client_identifier: str) -> Dict[str, Any]:
        """Retrieve every part ever quoted to a client, with all information sent to them."""
        clean_id = str(client_identifier or "").strip().lower()
        if not clean_id:
            return {"client_email": "", "total_parts_quoted": 0, "parts": {}, "quotes": []}

        conn = self._get_connection()
        conn.row_factory = None
        try:
            cursor = conn.cursor()
            query = """
                SELECT 
                    id, client_email, client_name, company_name, quote_number, rfq_id,
                    part_number, normalized_part_number, description, quantity, uom,
                    unit_price, total_price, currency, condition, certification,
                    lead_time, valid_until, status, sent_at, email_subject, email_body,
                    attachments, source_mailbox, source_message_id, created_at, updated_at
                FROM client_quote_history
                WHERE LOWER(client_email) = ? OR LOWER(company_name) = ? OR LOWER(client_name) = ?
                ORDER BY sent_at DESC, created_at DESC
            """
            cursor.execute(query, (clean_id, clean_id, clean_id))
            cols = [
                "id", "client_email", "client_name", "company_name", "quote_number", "rfq_id",
                "part_number", "normalized_part_number", "description", "quantity", "uom",
                "unit_price", "total_price", "currency", "condition", "certification",
                "lead_time", "valid_until", "status", "sent_at", "email_subject", "email_body",
                "attachments", "source_mailbox", "source_message_id", "created_at", "updated_at",
            ]
            rows = [dict(zip(cols, r)) for r in cursor.fetchall()]

            if not rows:
                return {
                    "client_identifier": client_identifier,
                    "client_email": clean_id,
                    "client_name": clean_id.split("@")[0].replace(".", " ").title() if "@" in clean_id else clean_id,
                    "company_name": clean_id.split("@")[1].split(".")[0].upper() if "@" in clean_id else clean_id,
                    "total_parts_quoted": 0,
                    "total_quotes": 0,
                    "total_quoted_value": 0.0,
                    "parts": {},
                    "quotes": [],
                }

            client_email = rows[0]["client_email"]
            client_name = rows[0]["client_name"]
            company_name = rows[0]["company_name"]

            parts_map: Dict[str, Dict[str, Any]] = {}
            for r in rows:
                pn = r["part_number"]
                norm_pn = r["normalized_part_number"]
                if norm_pn not in parts_map:
                    parts_map[norm_pn] = {
                        "part_number": pn,
                        "normalized_part_number": norm_pn,
                        "description": r["description"],
                        "times_quoted": 0,
                        "first_quoted_at": r["sent_at"],
                        "latest_quoted_at": r["sent_at"],
                        "latest_unit_price": r["unit_price"],
                        "latest_condition": r["condition"],
                        "latest_certification": r["certification"],
                        "quotes": [],
                    }
                entry = parts_map[norm_pn]
                entry["times_quoted"] += 1
                if r["sent_at"] > entry["latest_quoted_at"]:
                    entry["latest_quoted_at"] = r["sent_at"]
                    entry["latest_unit_price"] = r["unit_price"]
                    entry["latest_condition"] = r["condition"]
                    entry["latest_certification"] = r["certification"]
                if r["sent_at"] < entry["first_quoted_at"]:
                    entry["first_quoted_at"] = r["sent_at"]

                entry["quotes"].append({
                    "quote_number": r["quote_number"],
                    "rfq_id": r["rfq_id"],
                    "quantity": r["quantity"],
                    "uom": r["uom"],
                    "unit_price": r["unit_price"],
                    "total_price": r["total_price"],
                    "condition": r["condition"],
                    "certification": r["certification"],
                    "lead_time": r["lead_time"],
                    "valid_until": r["valid_until"],
                    "status": r["status"],
                    "sent_at": r["sent_at"],
                    "email_subject": r["email_subject"],
                    "email_body": r["email_body"],
                    "attachments": json.loads(r["attachments"]) if r["attachments"] else [],
                })

            total_val = sum(float(r["total_price"] or 0) for r in rows)
            return {
                "client_email": client_email,
                "client_name": client_name,
                "company_name": company_name,
                "total_parts_quoted": len(parts_map),
                "total_quotes": len(rows),
                "total_quoted_value": round(total_val, 2),
                "first_quoted_at": rows[-1]["sent_at"],
                "latest_quoted_at": rows[0]["sent_at"],
                "parts": parts_map,
                "quotes": rows,
            }
        finally:
            conn.close()

    def get_part_quote_history_for_client(self, client_email: str, part_number: str) -> List[Dict[str, Any]]:
        """Get every quote ever sent to a specific client for a given part number."""
        clean_email = str(client_email or "").strip().lower()
        norm_pn = _norm_pn(part_number)
        if not clean_email or not norm_pn:
            return []

        conn = self._get_connection()
        conn.row_factory = None
        try:
            cursor = conn.cursor()
            query = """
                SELECT 
                    id, client_email, client_name, company_name, quote_number, rfq_id,
                    part_number, normalized_part_number, description, quantity, uom,
                    unit_price, total_price, currency, condition, certification,
                    lead_time, valid_until, status, sent_at, email_subject, email_body,
                    attachments
                FROM client_quote_history
                WHERE LOWER(client_email) = ? AND normalized_part_number = ?
                ORDER BY sent_at DESC
            """
            cursor.execute(query, (clean_email, norm_pn))
            cols = [
                "id", "client_email", "client_name", "company_name", "quote_number", "rfq_id",
                "part_number", "normalized_part_number", "description", "quantity", "uom",
                "unit_price", "total_price", "currency", "condition", "certification",
                "lead_time", "valid_until", "status", "sent_at", "email_subject", "email_body",
                "attachments",
            ]
            return [dict(zip(cols, r)) for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_part_all_clients_history(self, part_number: str) -> List[Dict[str, Any]]:
        """Retrieve every client that has ever received a quote for a specific part number."""
        norm_pn = _norm_pn(part_number)
        if not norm_pn:
            return []

        conn = self._get_connection()
        conn.row_factory = None
        try:
            cursor = conn.cursor()
            query = """
                SELECT 
                    id, client_email, client_name, company_name, quote_number, rfq_id,
                    part_number, normalized_part_number, description, quantity, uom,
                    unit_price, total_price, currency, condition, certification,
                    lead_time, valid_until, status, sent_at, email_subject, email_body
                FROM client_quote_history
                WHERE normalized_part_number = ?
                ORDER BY sent_at DESC
            """
            cursor.execute(query, (norm_pn,))
            cols = [
                "id", "client_email", "client_name", "company_name", "quote_number", "rfq_id",
                "part_number", "normalized_part_number", "description", "quantity", "uom",
                "unit_price", "total_price", "currency", "condition", "certification",
                "lead_time", "valid_until", "status", "sent_at", "email_subject", "email_body",
            ]
            return [dict(zip(cols, r)) for r in cursor.fetchall()]
        finally:
            conn.close()

    def list_clients(self, search: str = "", limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List distinct clients with their quoted parts count, total quotes, and last quote date."""
        conn = self._get_connection()
        conn.row_factory = None
        try:
            cursor = conn.cursor()
            search_param = f"%{str(search or '').strip().lower()}%" if search else "%"
            query = """
                SELECT 
                    client_email,
                    MAX(client_name) AS client_name,
                    MAX(company_name) AS company_name,
                    COUNT(DISTINCT normalized_part_number) AS distinct_parts_quoted,
                    COUNT(*) AS total_quotes_sent,
                    COALESCE(SUM(total_price), 0) AS total_quoted_value,
                    MIN(sent_at) AS first_quote_date,
                    MAX(sent_at) AS latest_quote_date
                FROM client_quote_history
                WHERE LOWER(client_email) LIKE ? OR LOWER(COALESCE(company_name, '')) LIKE ? OR LOWER(COALESCE(client_name, '')) LIKE ?
                GROUP BY client_email
                ORDER BY latest_quote_date DESC
                LIMIT ? OFFSET ?
            """
            cursor.execute(query, (search_param, search_param, search_param, limit, offset))
            cols = [
                "client_email", "client_name", "company_name", "distinct_parts_quoted",
                "total_quotes_sent", "total_quoted_value", "first_quote_date", "latest_quote_date",
            ]
            return [dict(zip(cols, r)) for r in cursor.fetchall()]
        finally:
            conn.close()

    def parse_and_ingest_sent_email(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse an outbound email sent to a client and extract quoted parts, prices, and terms."""
        subject = str(message.get("subject") or "").strip()
        raw_body = str(message.get("body") or "").strip()
        sent_date = str(message.get("date") or message.get("receivedDateTime") or datetime.now(timezone.utc).isoformat())
        msg_id = str(message.get("message_id") or message.get("id") or "")

        # Extract recipients
        recipients = []
        if isinstance(message.get("toRecipients"), list):
            for r in message["toRecipients"]:
                addr = (r.get("emailAddress") or {}).get("address")
                name = (r.get("emailAddress") or {}).get("name")
                if addr and "@" in addr:
                    recipients.append((addr.lower(), name or ""))
        elif message.get("to"):
            to_val = str(message["to"])
            for part in to_val.split(","):
                part = part.strip()
                if "@" in part:
                    recipients.append((part.lower(), ""))

        if not recipients:
            return []

        # Convert HTML to clean text if necessary
        if "<html" in raw_body.lower() or "<div" in raw_body.lower():
            soup = BeautifulSoup(raw_body, "html.parser")
            body_text = soup.get_text(separator="\n").strip()
        else:
            body_text = raw_body

        # Extract quote number if available
        quote_num_match = re.search(r"\b(QTE-[A-Z0-9]{4,12}|PO-[A-Z0-9]{4,12}|WT-Q-[0-9]+)\b", f"{subject}\n{body_text}", re.I)
        quote_number = quote_num_match.group(1).upper() if quote_num_match else f"QTE-SENT-{uuid.uuid4().hex[:8].upper()}"

        rfq_match = re.search(r"\b(RFQ-[A-Z0-9]{4,12})\b", f"{subject}\n{body_text}", re.I)
        rfq_id = rfq_match.group(1).upper() if rfq_match else None

        # Check for structured bullet points:
        # - Part Number: ... \n - Description: ... \n - Quantity: ... \n - Unit Price: $...
        extracted_parts = []
        structured_matches = re.finditer(
            r"(?:[-*]\s*)?Part(?:\s*Number)?[:\s]+([A-Z0-9/_-]+)"
            r"(?:.*?Description[:\s]+([^\n]+))?"
            r"(?:.*?Quantity[:\s]+(\d+))?"
            r"(?:.*?Condition[:\s]+([A-Z0-9/_-]+))?"
            r"(?:.*?Cert(?:ification)?[:\s]+([^\n]+))?"
            r"(?:.*?(?:Unit\s*)?Price[:\s]+\$?\s*([\d,]+(?:\.\d{2})?))?"
            r"(?:.*?Lead(?:\s*Time)?[:\s]+([^\n]+))?",
            body_text,
            re.IGNORECASE | re.DOTALL,
        )
        for m in structured_matches:
            pn = m.group(1).strip()
            desc = (m.group(2) or pn).strip()
            qty = int(m.group(3) or 1)
            cond = (m.group(4) or "NE").strip()
            cert = (m.group(5) or "FAA 8130-3 / OEM CoC").strip()
            price_str = (m.group(6) or "0").replace(",", "").strip()
            lead = (m.group(7) or "Stock").strip()
            try:
                price = float(price_str)
            except ValueError:
                price = 0.0

            if _norm_pn(pn) and len(_norm_pn(pn)) >= 3:
                extracted_parts.append({
                    "part_number": pn,
                    "description": desc,
                    "quantity": qty,
                    "condition": cond,
                    "certification": cert,
                    "unit_price": price,
                    "lead_time": lead,
                })

        # Fallback: find any part number mentioned with price in text
        if not extracted_parts:
            pn_match = re.search(r"\b(?:part|PN|P/N)[:\s]+([A-Z0-9/_-]{4,25})\b", body_text, re.I)
            if not pn_match:
                pn_match = re.search(r"\b(?:part|PN|P/N)\s+([A-Z0-9/_-]{4,25})\b", subject, re.I)
            price_match = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", body_text)
            qty_match = re.search(r"\b(?:quantity|qty)[:\s]+(\d+)\b", body_text, re.I)

            if pn_match:
                pn = pn_match.group(1).strip()
                price = float(price_match.group(1).replace(",", "")) if price_match else 0.0
                qty = int(qty_match.group(1)) if qty_match else 1
                extracted_parts.append({
                    "part_number": pn,
                    "description": pn,
                    "quantity": qty,
                    "condition": "NE",
                    "certification": "FAA 8130-3 / OEM CoC",
                    "unit_price": price,
                    "lead_time": "Stock",
                })

        results = []
        for client_email, client_name in recipients:
            for part in extracted_parts:
                try:
                    record = self.record_client_quote(
                        client_email=client_email,
                        client_name=client_name,
                        quote_number=quote_number,
                        rfq_id=rfq_id,
                        part_number=part["part_number"],
                        description=part["description"],
                        quantity=part["quantity"],
                        unit_price=part["unit_price"],
                        total_price=part["unit_price"] * part["quantity"],
                        condition=part["condition"],
                        certification=part["certification"],
                        lead_time=part["lead_time"],
                        sent_at=sent_date,
                        email_subject=subject,
                        email_body=body_text[:4000],
                        source_message_id=msg_id,
                    )
                    results.append(record)
                except Exception as exc:
                    logger.warning("could_not_record_client_quote_from_email pn=%s err=%s", part.get("part_number"), exc)

        return results

    def sync_from_sales_mailbox(self, limit: int = 50, max_age_days: int = 180) -> Dict[str, Any]:
        """Fetch sent items from sales@wingedtycoons.com and ingest all quotes sent to clients."""
        token_configured = all(os.getenv(k) for k in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"))
        if not token_configured:
            logger.info("Graph API credentials not configured; skipping sales mailbox sync")
            return {"status": "skipped", "reason": "missing_graph_credentials", "records_ingested": 0}

        try:
            import requests
            from services.mailbox_service import _graph_access_token, _mailbox_user_for_graph

            token = _graph_access_token()
            user = _mailbox_user_for_graph("sales")
            headers = {"Authorization": f"Bearer {token}"}
            url = (
                f"https://graph.microsoft.com/v1.0/users/{user}/mailFolders/sentitems/messages"
                f"?$top={limit}&$select=id,subject,toRecipients,receivedDateTime,body"
                f"&$orderby=receivedDateTime desc"
            )
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            messages = resp.json().get("value", [])

            total_ingested = 0
            for msg in messages:
                body_content = (msg.get("body") or {}).get("content", "")
                parsed = self.parse_and_ingest_sent_email({
                    "id": msg.get("id"),
                    "subject": msg.get("subject"),
                    "toRecipients": msg.get("toRecipients"),
                    "receivedDateTime": msg.get("receivedDateTime"),
                    "body": body_content,
                })
                total_ingested += len(parsed)

            return {"status": "success", "messages_checked": len(messages), "records_ingested": total_ingested}
        except Exception as exc:
            logger.exception("sync_from_sales_mailbox_failed error=%s", exc)
            return {"status": "error", "error": str(exc), "records_ingested": 0}


client_history_service = ClientHistoryService()
