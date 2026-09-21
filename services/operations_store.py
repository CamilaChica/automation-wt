"""SQLite persistence for RFQ, quote, inventory, and audit state."""

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "operations.db"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


class OperationsStore:
    def __init__(self, path: str | Path | None = None):
        configured = path or os.getenv("OPERATIONS_DB_PATH")
        self.path = Path(configured) if configured else DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        try:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            self._ensure_column(conn, "automation_events", "idempotency_key", "TEXT")
            self._ensure_column(conn, "automation_events", "attempts", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "automation_events", "max_attempts", "INTEGER NOT NULL DEFAULT 3")
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def transaction(self):
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def load(self) -> Dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT payload FROM operations_state WHERE state_key = 'current'"
            ).fetchone()
        finally:
            conn.close()
        return json.loads(row[0]) if row else None

    def save(self, state: Dict[str, Any]) -> None:
        payload = json.dumps(state, separators=(",", ":"))
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO operations_state (state_key, payload) VALUES ('current', ?) "
                "ON CONFLICT(state_key) DO UPDATE SET payload = excluded.payload",
                (payload,),
            )

    def clear(self) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM operations_state WHERE state_key = 'current'")
            conn.commit()
        finally:
            conn.close()

    def record_communication(
        self,
        *,
        entity_type: str,
        entity_id: str,
        recipient: str,
        sender: str,
        channel: str,
        subject: str,
        message: str,
        message_type: str,
        status: str,
        response_received: str | None = None,
    ) -> str:
        communication_id = f"COM-{uuid.uuid4().hex[:12].upper()}"
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO communications "
                "(id, entity_type, entity_id, recipient, sender, channel, subject, message, "
                "message_type, status, sent_at, response_received, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    communication_id,
                    entity_type,
                    entity_id,
                    recipient,
                    sender,
                    channel,
                    subject,
                    message,
                    message_type,
                    status,
                    now if status == "SENT" else None,
                    response_received,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return communication_id

    def upsert_customer(self, customer_id: str, company_name: str, contact_name: str, email: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO customers (id, company_name, contact_name, email, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET company_name=excluded.company_name, contact_name=excluded.contact_name, email=excluded.email, updated_at=excluded.updated_at",
                (customer_id, company_name, contact_name, email, now, now),
            )
            conn.commit()
        finally:
            conn.close()

    def insert_rfq(self, *, rfq_id: str, customer_id: str, part_number: str | None, description: str, quantity: int, condition: str | None, certification: str | None, destination: str | None, status: str, raw_text: str, thread_id: str | None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO rfqs (id, customer_id, part_number, description, quantity, condition_requested, certification_requested, destination, status, raw_text, thread_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET customer_id=excluded.customer_id, part_number=COALESCE(excluded.part_number, rfqs.part_number), description=COALESCE(excluded.description, rfqs.description), quantity=COALESCE(excluded.quantity, rfqs.quantity), condition_requested=COALESCE(excluded.condition_requested, rfqs.condition_requested), certification_requested=COALESCE(excluded.certification_requested, rfqs.certification_requested), destination=COALESCE(excluded.destination, rfqs.destination), status=excluded.status, raw_text=COALESCE(excluded.raw_text, rfqs.raw_text), thread_id=COALESCE(excluded.thread_id, rfqs.thread_id), updated_at=excluded.updated_at",
                (rfq_id, customer_id, part_number, description, quantity, condition, certification, destination, status, raw_text, thread_id, now, now),
            )
            conn.commit()
        finally:
            conn.close()

    def update_rfq_status(self, rfq_id: str, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE rfqs SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, rfq_id),
            )
            conn.commit()
        finally:
            conn.close()

    def insert_customer_quote(self, *, quote_id: str, rfq_id: str, unit_price: float, quantity: int, total_price: float, lead_time: int | None, condition: str | None, certification: str | None, valid_until: str | None, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO customer_quotes (id, rfq_id, quote_number, unit_price, quantity, total_price, currency, lead_time, condition, certification, valid_until, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'USD', ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET unit_price=excluded.unit_price, quantity=excluded.quantity, total_price=excluded.total_price, lead_time=excluded.lead_time, condition=excluded.condition, certification=excluded.certification, valid_until=excluded.valid_until, status=excluded.status, updated_at=excluded.updated_at",
                (quote_id, rfq_id, quote_id, unit_price, quantity, total_price, lead_time, condition, certification, valid_until, status, now, now),
            )
            conn.commit()
        finally:
            conn.close()

    def insert_customer_quote_item(self, *, item_id: str, quote_id: str, rfq_item_id: str, part_number: str, description: str, quantity: int, condition: str | None, certification: str, unit_price: float, lead_time: int | None, attachments: str = "") -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO customer_quote_items (id, quote_id, rfq_item_id, part_number, description, quantity, condition, certification, unit_price, lead_time, attachments, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET description=excluded.description, quantity=excluded.quantity, condition=excluded.condition, certification=excluded.certification, unit_price=excluded.unit_price, lead_time=excluded.lead_time, attachments=excluded.attachments, updated_at=excluded.updated_at",
                (item_id, quote_id, rfq_item_id, part_number, description, quantity, condition, certification, unit_price, lead_time, attachments, now, now),
            )
            conn.commit()
        finally:
            conn.close()

    def record_automation_event(
        self,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
        status: str,
        result: str | None = None,
        error: str | None = None,
        idempotency_key: str | None = None,
        attempts: int = 0,
        max_attempts: int = 3,
    ) -> str:
        if idempotency_key:
            conn = self._connect()
            try:
                existing = conn.execute(
                    "SELECT id FROM automation_events WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
            finally:
                conn.close()
            if existing:
                return existing[0]
        event_id = f"AUT-{uuid.uuid4().hex[:12].upper()}"
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO automation_events "
                "(id, idempotency_key, event_type, entity_type, entity_id, status, attempts, max_attempts, execution_time, result, error, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, idempotency_key, event_type, entity_type, entity_id, status, attempts, max_attempts, now, result, error, now),
            )
            conn.commit()
        finally:
            conn.close()
        return event_id

    def update_automation_event(self, event_id: str, *, status: str, attempts: int, result: str | None = None, error: str | None = None) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE automation_events SET status = ?, attempts = ?, execution_time = ?, result = ?, error = ? WHERE id = ?",
                (status, attempts, datetime.now(timezone.utc).isoformat(), result, error, event_id),
            )
            conn.commit()
        finally:
            conn.close()

    def claim_carrier_webhook_event(self, event_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO carrier_webhook_events (event_id, received_at) VALUES (?, ?)",
                (event_id, now),
            )
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()

    def list_automation_events(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            if status:
                rows = conn.execute(
                    "SELECT * FROM automation_events WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, min(max(limit, 1), 500)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM automation_events ORDER BY created_at DESC LIMIT ?",
                    (min(max(limit, 1), 500),),
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()


operations_store = OperationsStore()
