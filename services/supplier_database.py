import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(os.getenv("SUPPLIER_DATABASE_PATH", str(Path(__file__).resolve().parent.parent / "data" / "supplier_email_store.db")))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SupplierDatabase:
    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS suppliers (
                    id TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    email TEXT,
                    phone TEXT,
                    approval_status TEXT NOT NULL DEFAULT 'Pending',
                    itar_certified INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'email',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS inbound_emails (
                    id TEXT PRIMARY KEY,
                    mailbox TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    sender TEXT,
                    subject TEXT,
                    body TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    processing_status TEXT NOT NULL DEFAULT 'received',
                    extraction_error TEXT,
                    UNIQUE(message_id)
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
                    confidence REAL,
                    approval_status TEXT NOT NULL DEFAULT 'Pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
                );

                CREATE INDEX IF NOT EXISTS idx_supplier_parts_part_number
                    ON supplier_parts(part_number);

                CREATE INDEX IF NOT EXISTS idx_supplier_parts_supplier_id
                    ON supplier_parts(supplier_id);

                CREATE TABLE IF NOT EXISTS communication_tasks (
                    id TEXT PRIMARY KEY,
                    task_key TEXT NOT NULL UNIQUE,
                    task_type TEXT NOT NULL,
                    mailbox TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    reply_to TEXT,
                    due_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    sent_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_communication_tasks_due
                    ON communication_tasks(status, due_at);
                """
            )
            for column, definition in (
                ("description", "TEXT"),
                ("availability_location", "TEXT"),
                ("warranty_terms", "TEXT"),
                ("trace_documents", "TEXT"),
            ):
                existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(supplier_parts)")}
                if column not in existing_columns:
                    conn.execute(f"ALTER TABLE supplier_parts ADD COLUMN {column} {definition}")

    def upsert_supplier(self, supplier_name: str, supplier_email: Optional[str] = None, phone: Optional[str] = None, approval_status: str = "Pending") -> str:
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT id FROM suppliers WHERE company_name = ? OR email = ?",
                (supplier_name, supplier_email or ""),
            ).fetchone()
            if existing:
                supplier_id = existing["id"]
                conn.execute(
                    "UPDATE suppliers SET email = COALESCE(?, email), phone = COALESCE(?, phone), approval_status = ?, updated_at = ? WHERE id = ?",
                    (supplier_email, phone, approval_status, _now_iso(), supplier_id),
                )
                return supplier_id

            supplier_id = f"SUP-{uuid.uuid4().hex[:8].upper()}"
            conn.execute(
                "INSERT INTO suppliers (id, company_name, email, phone, approval_status, itar_certified, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (supplier_id, supplier_name, supplier_email, phone, approval_status, 0, "email", _now_iso(), _now_iso()),
            )
            return supplier_id

    def save_email(self, mailbox: str, message_id: str, sender: str, subject: str, body: str, received_at: Optional[str] = None) -> str:
        if not received_at:
            received_at = _now_iso()
        email_id = f"EML-{uuid.uuid4().hex[:8].upper()}"
        with self._connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO inbound_emails (id, mailbox, message_id, sender, subject, body, received_at, processing_status) VALUES (?, ?, ?, ?, ?, ?, ?, 'processed')",
                (email_id, mailbox, message_id, sender, subject, body, received_at),
            )
        return email_id

    def is_email_processed(self, mailbox: str, message_id: str) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT processing_status FROM inbound_emails WHERE mailbox = ? AND message_id = ?",
                (mailbox, message_id),
            ).fetchone()
        return bool(row and row["processing_status"] == "processed")

    def save_supplier_offer(
        self,
        supplier_name: str,
        supplier_email: Optional[str] = None,
        part_number: str = "",
        quantity_available: Optional[int] = None,
        unit_cost: Optional[float] = None,
        certificate_type: Optional[str] = None,
        lead_time_days: Optional[int] = None,
        approval_status: str = "Pending",
        condition_code: Optional[str] = None,
        source_email_id: Optional[str] = None,
        confidence: float = 1.0,
        description: str = "",
        availability_location: Optional[str] = None,
        warranty_terms: Optional[str] = None,
        trace_documents: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        supplier_id = self.upsert_supplier(supplier_name, supplier_email=supplier_email, approval_status=approval_status)
        offer_id = f"SPO-{uuid.uuid4().hex[:8].upper()}"
        now = _now_iso()
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT id FROM supplier_parts WHERE supplier_id = ? AND part_number = ?",
                (supplier_id, part_number.upper()),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE supplier_parts SET description = ?, quantity_available = ?, unit_cost = ?, currency = ?, certificate_type = ?, lead_time_days = ?, availability_location = ?, warranty_terms = ?, trace_documents = ?, approval_status = ?, condition_code = ?, source_email_id = ?, confidence = ?, updated_at = ? WHERE id = ?",
                    (description, quantity_available, unit_cost, "USD", certificate_type, lead_time_days, availability_location, warranty_terms, json.dumps(trace_documents or []), approval_status, condition_code, source_email_id, confidence, now, existing["id"]),
                )
                offer_id = existing["id"]
            else:
                conn.execute(
                    "INSERT INTO supplier_parts (id, supplier_id, part_number, condition_code, description, quantity_available, unit_cost, currency, certificate_type, lead_time_days, availability_location, warranty_terms, trace_documents, source_email_id, confidence, approval_status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (offer_id, supplier_id, part_number.upper(), condition_code, description, quantity_available, unit_cost, "USD", certificate_type, lead_time_days, availability_location, warranty_terms, json.dumps(trace_documents or []), source_email_id, confidence, approval_status, now, now),
                )

        return {
            "id": offer_id,
            "supplier_id": supplier_id,
            "supplier_name": supplier_name,
            "part_number": part_number.upper(),
            "quantity_available": quantity_available,
            "unit_cost": unit_cost,
            "certificate_type": certificate_type,
            "lead_time_days": lead_time_days,
            "approval_status": approval_status,
            "condition_code": condition_code,
            "source_email_id": source_email_id,
            "confidence": confidence,
        }

    def find_supplier_offers(self, part_number: str, quantity_needed: int = 1) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT sp.id AS supplier_part_id, sp.supplier_id, sp.part_number, sp.quantity_available, sp.unit_cost,
                       sp.certificate_type, sp.lead_time_days, sp.condition_code, sp.approval_status,
                       sp.confidence, sp.updated_at, sp.source_email_id, s.company_name AS supplier_name,
                       s.email AS supplier_email, s.approval_status AS supplier_approval_status
                FROM supplier_parts sp
                JOIN suppliers s ON s.id = sp.supplier_id
                WHERE sp.part_number = ?
                  AND (sp.quantity_available IS NULL OR sp.quantity_available >= ?)
                  AND (sp.approval_status = 'Approved' OR s.approval_status = 'Approved')
                ORDER BY CASE WHEN sp.source_email_id IS NOT NULL THEN 1 ELSE 0 END DESC,
                         sp.updated_at DESC,
                         sp.unit_cost ASC,
                         sp.lead_time_days ASC
                LIMIT 10
                """,
                (part_number.upper(), max(1, quantity_needed)),
            ).fetchall()

        return [dict(row) for row in rows]

    def get_supplier_offers_for_part(self, part_number: str) -> List[Dict[str, Any]]:
        return self.find_supplier_offers(part_number, quantity_needed=1)

    def list_suppliers(self) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM suppliers ORDER BY company_name ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def schedule_communication_task(
        self,
        task_key: str,
        task_type: str,
        mailbox: str,
        recipient: str,
        subject: str,
        body: str,
        due_at: str,
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        task_id = f"COM-{uuid.uuid4().hex[:8].upper()}"
        now = _now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO communication_tasks
                (id, task_key, task_type, mailbox, recipient, subject, body, reply_to, due_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, task_key, task_type, mailbox, recipient, subject, body, reply_to, due_at, now),
            )
            row = conn.execute(
                "SELECT * FROM communication_tasks WHERE task_key = ?", (task_key,)
            ).fetchone()
        return dict(row)

    def list_due_communication_tasks(self, now: Optional[str] = None) -> List[Dict[str, Any]]:
        now = now or _now_iso()
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM communication_tasks WHERE status = 'pending' AND due_at <= ? ORDER BY due_at ASC",
                (now,),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_communication_task_sent(self, task_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE communication_tasks SET status = 'sent', attempts = attempts + 1, sent_at = ? WHERE id = ?",
                (_now_iso(), task_id),
            )

    def mark_communication_task_failed(self, task_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE communication_tasks SET status = 'failed', attempts = attempts + 1 WHERE id = ?",
                (task_id,),
            )

    def cancel_communication_task(self, task_key: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE communication_tasks SET status = 'cancelled' WHERE task_key = ? AND status = 'pending'",
                (task_key,),
            )

    def reset_supplier_data(self) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM communication_tasks")
            conn.execute("DELETE FROM supplier_parts")
            conn.execute("DELETE FROM suppliers")
            conn.execute("DELETE FROM inbound_emails")


supplier_db = SupplierDatabase()
