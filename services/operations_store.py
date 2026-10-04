"""SQLite persistence for RFQ, quote, inventory, and audit state."""

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from repositories.review_telemetry_repository import (
    PostgresReviewTelemetryRepository,
    inbound_dedupe_key,
    inventory_import_record_id,
    raw_email_record_id,
)


DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "operations.db"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"
POSTGRES_STORE_METHODS = (
    "load_operations_state",
    "save_operations_state",
    "clear_operations_state",
    "claim_inbound_message",
    "mark_inbound_message_processed",
    "save_inbound_email",
    "is_inbound_email_processed",
    "release_inbound_message",
    "save_raw_email",
    "set_raw_email_processing_status",
    "get_raw_email_mime",
    "record_audit_event",
    "insert_audit_log",
    "list_audit_logs",
    "inventory_import_exists",
    "record_inventory_import",
    "record_inventory_rows",
    "record_purchase_order",
    "list_purchase_orders",
    "update_purchase_order_status",
    "get_negotiation_session",
    "save_negotiation_session",
    "get_operational_record",
    "lock_operational_record",
    "list_operational_records",
    "save_operational_record",
    "delete_operational_record",
    "reserve_inventory",
    "check_operational_schema",
    "transaction",
    "record_communication",
    "upsert_customer",
    "insert_rfq",
    "update_rfq_status",
    "insert_customer_quote",
    "insert_customer_quote_item",
    "update_customer_quote_status",
    "record_automation_event",
    "update_automation_event",
    "claim_automation_events",
    "claim_carrier_webhook_event",
    "list_automation_events",
    "get_automation_event",
    "enqueue_operator_review",
    "get_operator_review",
    "list_operator_reviews",
    "link_operator_review_entity",
    "add_operator_review_flags",
    "claim_operator_review_decision",
    "complete_operator_review_decision",
    "record_llm_telemetry",
    "list_llm_telemetry",
    "enqueue_outbox_message",
    "claim_outbox_messages",
    "mark_outbox_sent",
    "fail_outbox_message",
    "recover_stale_outbox_messages",
    "upsert_supplier",
    "list_suppliers",
    "save_supplier_offer",
    "get_supplier_offers",
    "search_supplier_offers",
    "schedule_communication_task",
    "list_due_communication_tasks",
    "update_communication_task",
    "retry_communication_task",
    "list_dead_letter_communication_tasks",
    "cancel_communication_task",
)


class OperationsStore:
    def __init__(self, path: str | Path | None = None):
        production = any(
            os.getenv(name, "").strip().lower() == "production"
            for name in ("ENVIRONMENT", "WT_ENV", "WT_AUTH_ENV")
        ) or os.getenv("RENDER", "false").strip().lower() in {"1", "true", "yes", "on"}
        if production and not os.getenv("DATABASE_URL", "").strip():
            raise RuntimeError("DATABASE_URL is required for production operational persistence.")
        if production:
            self.path = None
            self._postgres = PostgresReviewTelemetryRepository()
            missing_methods = [
                method for method in POSTGRES_STORE_METHODS
                if not callable(getattr(self._postgres, method, None))
            ]
            if missing_methods:
                raise RuntimeError(
                    "PostgreSQL operational adapter is incomplete: " + ", ".join(missing_methods)
                )
            return
        self._postgres = None
        configured = path or os.getenv("OPERATIONS_DB_PATH")
        self.path = Path(configured) if configured else DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        try:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            self._ensure_column(conn, "automation_events", "idempotency_key", "TEXT")
            self._ensure_column(conn, "automation_events", "attempts", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "automation_events", "max_attempts", "INTEGER NOT NULL DEFAULT 3")
            self._ensure_column(conn, "operator_review_queue", "prompt_version", "TEXT")
            for column, definition in (
                ("rfq_id", "TEXT"),
                ("customer_email", "TEXT"),
                ("total_amount", "REAL"),
                ("po_document_url", "TEXT"),
                ("received_message_id", "TEXT"),
                ("attachment_metadata", "TEXT"),
            ):
                self._ensure_column(conn, "purchase_orders", column, definition)
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_purchase_orders_received_message ON purchase_orders(received_message_id) WHERE received_message_id IS NOT NULL")
            conn.commit()
        finally:
            conn.close()

    @property
    def storage_engine(self) -> str:
        return "postgresql" if self._postgres else "sqlite"

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _connect(self) -> sqlite3.Connection:
        if self._postgres:
            raise RuntimeError(
                "This operation is not wired to the production PostgreSQL repository; refusing SQLite fallback."
            )
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def transaction(self):
        if self._postgres:
            with self._postgres.transaction() as connection:
                yield connection
            return
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
        if self._postgres:
            return self._postgres.load_operations_state()
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT payload FROM operations_state WHERE state_key = 'current'"
            ).fetchone()
        finally:
            conn.close()
        return json.loads(row[0]) if row else None

    def save(self, state: Dict[str, Any]) -> None:
        if self._postgres:
            self._postgres.save_operations_state(state)
            return
        payload = json.dumps(state, separators=(",", ":"))
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO operations_state (state_key, payload) VALUES ('current', ?) "
                "ON CONFLICT(state_key) DO UPDATE SET payload = excluded.payload",
                (payload,),
            )

    def clear(self) -> None:
        if self._postgres:
            self._postgres.clear_operations_state()
            return
        conn = self._connect()
        try:
            conn.execute("DELETE FROM operations_state WHERE state_key = 'current'")
            conn.commit()
        finally:
            conn.close()

    def claim_inbound_message(self, message_id: str, mailbox: str, internet_message_id: str | None = None) -> bool:
        if self._postgres:
            if internet_message_id is None:
                return self._postgres.claim_inbound_message(message_id, mailbox)
            return self._postgres.claim_inbound_message(message_id, mailbox, internet_message_id)
        secondary_key = inbound_dedupe_key(internet_message_id)
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            claim = (
                "INSERT OR IGNORE INTO inbound_message_idempotency (message_id, mailbox, processed_at, status) "
                "VALUES (?, ?, ?, 'processing')"
            )
            if conn.execute(claim, (message_id, mailbox, now)).rowcount != 1:
                return False
            if secondary_key and conn.execute(claim, (secondary_key, mailbox, now)).rowcount != 1:
                conn.execute(
                    "UPDATE inbound_message_idempotency SET status = 'duplicate' WHERE message_id = ?",
                    (message_id,),
                )
                return False
            return True
        finally:
            conn.commit()
            conn.close()

    def mark_inbound_message_processed(self, message_id: str, internet_message_id: str | None = None) -> None:
        if self._postgres:
            if internet_message_id is None:
                self._postgres.mark_inbound_message_processed(message_id)
                return
            self._postgres.mark_inbound_message_processed(message_id, internet_message_id)
            return
        conn = self._connect()
        try:
            for key in filter(None, (message_id, inbound_dedupe_key(internet_message_id))):
                conn.execute(
                    "UPDATE inbound_message_idempotency SET status = 'processed', processed_at = ? WHERE message_id = ?",
                    (datetime.now(timezone.utc).isoformat(), key),
                )
            conn.commit()
        finally:
            conn.close()

    def save_inbound_email(self, *, mailbox: str, message_id: str, sender: str, subject: str, body: str, processing_status: str = "processed") -> str:
        if self._postgres:
            return self._postgres.save_inbound_email(
                mailbox=mailbox, message_id=message_id, sender=sender, subject=subject,
                body=body, processing_status=processing_status,
            )
        raise RuntimeError("Shared inbound email persistence requires PostgreSQL mode.")

    def is_inbound_email_processed(self, mailbox: str, message_id: str) -> bool:
        if self._postgres:
            return self._postgres.is_inbound_email_processed(mailbox, message_id)
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT processing_status FROM inbound_emails WHERE mailbox = ? AND message_id = ?",
                (mailbox, message_id),
            ).fetchone()
            return bool(row and row["processing_status"] == "processed")
        finally:
            conn.close()

    def release_inbound_message(self, message_id: str, internet_message_id: str | None = None) -> None:
        if self._postgres:
            if internet_message_id is None:
                self._postgres.release_inbound_message(message_id)
                return
            self._postgres.release_inbound_message(message_id, internet_message_id)
            return
        conn = self._connect()
        try:
            for key in filter(None, (message_id, inbound_dedupe_key(internet_message_id))):
                conn.execute(
                    "DELETE FROM inbound_message_idempotency WHERE message_id = ? AND status = 'processing'",
                    (key,),
                )
            conn.commit()
        finally:
            conn.close()

    def save_raw_email(
        self,
        *,
        mailbox: str,
        provider_message_id: str,
        internet_message_id: str | None = None,
        conversation_id: str | None = None,
        sender: str | None = None,
        subject: str | None = None,
        received_at: datetime | None = None,
        body: str = "",
        raw_mime: bytes | None = None,
        headers: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        processing_status: str = "received",
    ) -> str:
        if self._postgres:
            return self._postgres.save_raw_email(
                mailbox=mailbox, provider_message_id=provider_message_id,
                internet_message_id=internet_message_id, conversation_id=conversation_id,
                sender=sender, subject=subject, received_at=received_at, body=body,
                raw_mime=raw_mime, headers=headers, attachments=attachments,
                processing_status=processing_status,
            )
        raw_email_id = raw_email_record_id(mailbox, provider_message_id)
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO raw_emails (id, mailbox, provider_message_id, internet_message_id, conversation_id, "
                "sender, subject, received_at, body, raw_mime, headers, attachments, processing_status, archived_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (mailbox, provider_message_id) DO UPDATE SET "
                "processing_status = excluded.processing_status, "
                "raw_mime = COALESCE(excluded.raw_mime, raw_emails.raw_mime)",
                (
                    raw_email_id, mailbox, provider_message_id, internet_message_id, conversation_id,
                    sender, subject, received_at.isoformat() if received_at else None, body or "",
                    raw_mime, json.dumps(headers) if headers is not None else None,
                    json.dumps(attachments) if attachments is not None else None,
                    processing_status, datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return raw_email_id

    def get_raw_email_mime(self, source_message_id: str, mailbox: str = "purchasing") -> bytes | None:
        if self._postgres:
            return self._postgres.get_raw_email_mime(source_message_id, mailbox=mailbox)
        source_id = str(source_message_id or "").strip()
        if not source_id:
            return None
        candidates = list(dict.fromkeys((source_id, source_id.split(":", 1)[0])))
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT raw_mime FROM raw_emails WHERE mailbox = ? AND provider_message_id IN (?, ?) "
                "ORDER BY CASE WHEN provider_message_id = ? THEN 0 ELSE 1 END LIMIT 1",
                (mailbox, candidates[0], candidates[-1], source_id),
            ).fetchone()
            return bytes(row["raw_mime"]) if row and row["raw_mime"] is not None else None
        finally:
            conn.close()

    def set_raw_email_processing_status(
        self, mailbox: str, provider_message_id: str, processing_status: str,
    ) -> None:
        if self._postgres:
            self._postgres.set_raw_email_processing_status(
                mailbox, provider_message_id, processing_status
            )
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE raw_emails SET processing_status = ? "
                "WHERE mailbox = ? AND provider_message_id = ?",
                (processing_status, mailbox, provider_message_id),
            )

    def record_audit_event(self, *, entity_id: str, actor: str, action: str, status: str, payload: dict[str, Any] | None = None) -> str:
        if self._postgres:
            return self._postgres.record_audit_event(
                entity_id=entity_id, actor=actor, action=action, status=status, payload=payload,
            )
        audit_id = f"AUD-{uuid.uuid4().hex[:24].upper()}"
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO audit_events (id, entity_id, actor, action, status, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    audit_id, entity_id, actor, action, status,
                    json.dumps(payload) if payload is not None else None,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return audit_id

    def insert_audit_log(self, *, rfq_id: str, agent_name: str, action_type: str, message: str, status: str, payload_json: str | None, timestamp: datetime) -> dict[str, Any]:
        if self._postgres:
            return self._postgres.insert_audit_log(
                rfq_id=rfq_id, agent_name=agent_name, action_type=action_type, message=message,
                status=status, payload_json=payload_json, timestamp=timestamp,
            )
        conn = self._connect()
        try:
            cursor = conn.execute(
                "INSERT INTO audit_logs (rfq_id, agent_name, action_type, message, status, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rfq_id, agent_name, action_type, message, status, payload_json, timestamp.isoformat()),
            )
            conn.commit()
            return {"id": int(cursor.lastrowid), "timestamp": timestamp}
        finally:
            conn.close()

    def list_audit_logs(self, rfq_id: str) -> list[dict[str, Any]]:
        if self._postgres:
            return self._postgres.list_audit_logs(rfq_id)
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, rfq_id, agent_name, action_type, message, status, payload_json, created_at AS timestamp "
                "FROM audit_logs WHERE rfq_id = ? ORDER BY id", (rfq_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def list_audit_events(self, entity_id: str) -> list[dict[str, Any]]:
        if self._postgres:
            raise RuntimeError("Audit event listing is served from operational records in PostgreSQL mode.")
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM audit_events WHERE entity_id = ? ORDER BY created_at, rowid",
                (entity_id,),
            ).fetchall()
        finally:
            conn.close()
        return [{**dict(row), "payload": json.loads(row["payload"]) if row["payload"] else None} for row in rows]

    def inventory_import_exists(self, source_message_id: str, content_sha256: str) -> bool:
        if self._postgres:
            return self._postgres.inventory_import_exists(source_message_id, content_sha256)
        conn = self._connect()
        try:
            return conn.execute(
                "SELECT 1 FROM supplier_inventory_imports WHERE source_message_id = ? AND content_sha256 = ?",
                (source_message_id, content_sha256),
            ).fetchone() is not None
        finally:
            conn.close()

    def record_inventory_import(self, **record: Any) -> str:
        if self._postgres:
            return self._postgres.record_inventory_import(**record)
        import_id = inventory_import_record_id(record["source_message_id"], record["content_sha256"])
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO supplier_inventory_imports (id, mailbox, source_message_id, sender, filename, "
                "content_sha256, parser, sheet_name, header_map, rows_total, rows_imported, rows_rejected, "
                "rejected_rows, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    import_id, record["mailbox"], record["source_message_id"], record.get("sender"),
                    record["filename"], record["content_sha256"], record["parser"], record.get("sheet_name"),
                    json.dumps(record.get("header_map")), record.get("rows_total", 0),
                    record.get("rows_imported", 0), record.get("rows_rejected", 0),
                    json.dumps(record.get("rejected_rows")), record["status"],
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return import_id

    def record_inventory_rows(self, import_id: str, rows: list[dict[str, Any]]) -> None:
        if self._postgres:
            self._postgres.record_inventory_rows(import_id, rows)
            return
        conn = self._connect()
        try:
            conn.executemany(
                "INSERT OR REPLACE INTO supplier_inventory_rows "
                "(id, import_id, row_number, part_number, description, quantity_available, condition_code, "
                "unit_price, currency, lead_time_days, certificate_type, availability_location, raw_values, status, error, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(
                    row["id"], import_id, row["row_number"], row.get("part_number"), row.get("description"),
                    row.get("quantity_available"), row.get("condition_code"), row.get("unit_price"),
                    row.get("currency"), row.get("lead_time_days"), row.get("certificate_type"),
                    row.get("availability_location"), json.dumps(row.get("raw_values") or {}),
                    row["status"], row.get("error"), datetime.now(timezone.utc).isoformat(),
                ) for row in rows],
            )
            conn.commit()
        finally:
            conn.close()

    def record_purchase_order(self, *, po_id: str, po_number: str, customer_email: str, total_amount: float, status: str, quote_id: str, rfq_id: str, received_message_id: str | None, attachment_metadata: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if self._postgres:
            return self._postgres.record_purchase_order(
                po_id=po_id, po_number=po_number, customer_email=customer_email, total_amount=total_amount,
                status=status, quote_id=quote_id, rfq_id=rfq_id, received_message_id=received_message_id,
                attachment_metadata=attachment_metadata or [],
            )
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO purchase_orders "
                "(id, quote_id, rfq_id, po_number, customer_email, amount, total_amount, currency, status, "
                "received_message_id, attachment_metadata, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'USD', ?, ?, ?, ?, ?)",
                (
                    po_id, quote_id, rfq_id, po_number, customer_email, total_amount, total_amount, status,
                    received_message_id, json.dumps(attachment_metadata or []),
                    datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(),
                ),
            )
            row = conn.execute("SELECT * FROM purchase_orders WHERE po_number = ?", (po_number,)).fetchone()
            conn.commit()
            return dict(row) if row else {}
        finally:
            conn.close()

    def list_purchase_orders(self, *, status: str = "Pending_PO_Review") -> list[dict[str, Any]]:
        if self._postgres:
            return self._postgres.list_purchase_orders(status=status)
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, po_number, customer_email, total_amount, status, quote_id, rfq_id, attachment_metadata, created_at "
                "FROM purchase_orders WHERE status = ? ORDER BY created_at ASC",
                (status,),
            ).fetchall()
            purchase_orders = []
            for row in rows:
                record = dict(row)
                metadata = record.get("attachment_metadata")
                record["attachment_metadata"] = json.loads(metadata) if isinstance(metadata, str) and metadata else metadata or []
                purchase_orders.append(record)
            return purchase_orders
        finally:
            conn.close()

    def update_purchase_order_status(self, quote_id: str, status: str) -> bool:
        if self._postgres:
            return self._postgres.update_purchase_order_status(quote_id, status)
        conn = self._connect()
        try:
            result = conn.execute(
                "UPDATE purchase_orders SET status = ?, updated_at = ? WHERE quote_id = ? AND status = 'Pending_PO_Review'",
                (status, datetime.now(timezone.utc).isoformat(), quote_id),
            )
            conn.commit()
            return result.rowcount > 0
        finally:
            conn.close()

    def get_negotiation_session(self, supplier_email: str, part_number: str) -> dict[str, Any] | None:
        if self._postgres:
            return self._postgres.get_negotiation_session(supplier_email, part_number)
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT payload FROM negotiation_sessions WHERE supplier_email = ? AND part_number = ?",
                (supplier_email.lower(), part_number.upper()),
            ).fetchone()
            return json.loads(row["payload"]) if row else None
        finally:
            conn.close()

    def save_negotiation_session(self, *, session_id: str, supplier_email: str, part_number: str, payload: dict[str, Any]) -> None:
        if self._postgres:
            self._postgres.save_negotiation_session(
                session_id=session_id, supplier_email=supplier_email, part_number=part_number, payload=payload,
            )
            return
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO negotiation_sessions (id, supplier_email, part_number, payload, updated_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(supplier_email, part_number) DO UPDATE SET "
                "payload = excluded.payload, updated_at = excluded.updated_at",
                (session_id, supplier_email.lower(), part_number.upper(), json.dumps(payload), datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def get_operational_record(self, domain: str, record_id: str) -> dict[str, Any] | None:
        if not self._postgres:
            raise RuntimeError("Per-record shared persistence is only available in PostgreSQL mode.")
        return self._postgres.get_operational_record(domain, record_id)

    def lock_operational_record(self, domain: str, record_id: str) -> dict[str, Any] | None:
        if not self._postgres:
            raise RuntimeError("Operational row locking requires PostgreSQL mode.")
        return self._postgres.lock_operational_record(domain, record_id)

    def list_operational_records(self, domain: str) -> dict[str, dict[str, Any]]:
        if not self._postgres:
            raise RuntimeError("Per-record shared persistence is only available in PostgreSQL mode.")
        return self._postgres.list_operational_records(domain)

    def save_operational_record(self, domain: str, record_id: str, payload: dict[str, Any]) -> None:
        if not self._postgres:
            raise RuntimeError("Per-record shared persistence is only available in PostgreSQL mode.")
        self._postgres.save_operational_record(domain, record_id, payload)

    def delete_operational_record(self, domain: str, record_id: str) -> None:
        if not self._postgres:
            raise RuntimeError("Per-record shared persistence is only available in PostgreSQL mode.")
        self._postgres.delete_operational_record(domain, record_id)

    def reserve_inventory(self, part_number: str, quantity: int) -> bool:
        if not self._postgres:
            raise RuntimeError("Atomic shared inventory reservation requires PostgreSQL mode.")
        return self._postgres.reserve_inventory(part_number, quantity)

    def check_operational_schema(self) -> dict[str, Any]:
        if not self._postgres:
            return {"ready": False, "missing_tables": ["postgresql operational schema"]}
        return self._postgres.check_operational_schema()

    def enqueue_outbox_message(self, **message: Any) -> dict[str, Any]:
        if not self._postgres:
            raise RuntimeError("Transactional outbox requires PostgreSQL mode.")
        return self._postgres.enqueue_outbox_message(**message)

    def claim_outbox_messages(self, *, limit: int = 25) -> list[dict[str, Any]]:
        if not self._postgres:
            return []
        return self._postgres.claim_outbox_messages(limit=limit)

    def mark_outbox_sent(self, message_id: str) -> None:
        if not self._postgres:
            raise RuntimeError("Transactional outbox requires PostgreSQL mode.")
        self._postgres.mark_outbox_sent(message_id)

    def fail_outbox_message(self, message_id: str, error: str, *, retryable: bool = False) -> str:
        if not self._postgres:
            raise RuntimeError("Transactional outbox requires PostgreSQL mode.")
        return self._postgres.fail_outbox_message(message_id, error, retryable=retryable)

    def recover_stale_outbox_messages(self, *, sending_timeout_seconds: int = 300) -> int:
        if not self._postgres:
            return 0
        return self._postgres.recover_stale_outbox_messages(sending_timeout_seconds=sending_timeout_seconds)

    def upsert_supplier(self, supplier_name: str, supplier_email: str | None = None, phone: str | None = None, approval_status: str = "Pending") -> str:
        if not self._postgres:
            raise RuntimeError("Shared supplier registry requires PostgreSQL mode.")
        return self._postgres.upsert_supplier(supplier_name, supplier_email, phone, approval_status)

    def list_suppliers(self) -> list[dict[str, Any]]:
        if not self._postgres:
            raise RuntimeError("Shared supplier registry requires PostgreSQL mode.")
        return self._postgres.list_suppliers()

    def save_supplier_offer(self, **offer: Any) -> dict[str, Any]:
        if not self._postgres:
            raise RuntimeError("Shared supplier offers require PostgreSQL mode.")
        return self._postgres.save_supplier_offer(**offer)

    def get_supplier_offers(self, part_number: str, quantity_needed: int = 1) -> list[dict[str, Any]]:
        if not self._postgres:
            raise RuntimeError("Shared supplier offers require PostgreSQL mode.")
        return self._postgres.get_supplier_offers(part_number, quantity_needed)

    def search_supplier_offers(self, query: str, condition: str | None = None) -> list[dict[str, Any]]:
        if not self._postgres:
            raise RuntimeError("Shared supplier offers require PostgreSQL mode.")
        return self._postgres.search_supplier_offers(query, condition)

    def list_inventory_catalog(self, limit: int = 500) -> list[dict[str, Any]]:
        if not self._postgres:
            return []
        return self._postgres.list_inventory_catalog(limit)

    def schedule_communication_task(self, **task: Any) -> dict[str, Any]:
        if not self._postgres:
            raise RuntimeError("Shared communication tasks require PostgreSQL mode.")
        return self._postgres.schedule_communication_task(**task)

    def list_due_communication_tasks(self, now: datetime | None = None) -> list[dict[str, Any]]:
        if not self._postgres:
            raise RuntimeError("Shared communication tasks require PostgreSQL mode.")
        return self._postgres.list_due_communication_tasks(now)

    def update_communication_task(self, task_id: str, *, status: str, error: str | None = None) -> None:
        if not self._postgres:
            raise RuntimeError("Shared communication tasks require PostgreSQL mode.")
        self._postgres.update_communication_task(task_id, status=status, error=error)

    def retry_communication_task(self, task_id: str, error: str) -> None:
        if not self._postgres:
            raise RuntimeError("Shared communication tasks require PostgreSQL mode.")
        self._postgres.retry_communication_task(task_id, error)

    def list_dead_letter_communication_tasks(self) -> list[dict[str, Any]]:
        if self._postgres:
            return self._postgres.list_dead_letter_communication_tasks()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM communication_tasks WHERE status = 'dead_letter' ORDER BY created_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def cancel_communication_task(self, task_key: str) -> None:
        if self._postgres:
            self._postgres.cancel_communication_task(task_key)
            return
        conn = self._connect()
        try:
            conn.execute("UPDATE communication_tasks SET status = 'cancelled' WHERE task_key = ? AND status = 'pending'", (task_key,))
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
        if self._postgres:
            return self._postgres.record_communication(
                entity_type=entity_type,
                entity_id=entity_id,
                recipient=recipient,
                sender=sender,
                channel=channel,
                subject=subject,
                message=message,
                message_type=message_type,
                status=status,
                response_received=response_received,
            )
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
        if self._postgres:
            self._postgres.upsert_customer(customer_id, company_name, contact_name, email)
            return
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
        if self._postgres:
            self._postgres.insert_rfq(
                rfq_id=rfq_id,
                customer_id=customer_id,
                part_number=part_number,
                description=description,
                quantity=quantity,
                condition=condition,
                certification=certification,
                destination=destination,
                status=status,
                raw_text=raw_text,
                thread_id=thread_id,
            )
            return
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
        if self._postgres:
            self._postgres.update_rfq_status(rfq_id, status)
            return
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
        if self._postgres:
            self._postgres.insert_customer_quote(
                quote_id=quote_id,
                rfq_id=rfq_id,
                unit_price=unit_price,
                quantity=quantity,
                total_price=total_price,
                lead_time=lead_time,
                condition=condition,
                certification=certification,
                valid_until=valid_until,
                status=status,
            )
            return
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
        if self._postgres:
            self._postgres.insert_customer_quote_item(
                item_id=item_id,
                quote_id=quote_id,
                rfq_item_id=rfq_item_id,
                part_number=part_number,
                description=description,
                quantity=quantity,
                condition=condition,
                certification=certification,
                unit_price=unit_price,
                lead_time=lead_time,
                attachments=attachments,
            )
            return
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

    def update_customer_quote_status(self, quote_id: str, status: str) -> None:
        if self._postgres:
            self._postgres.update_customer_quote_status(quote_id, status)
            return
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE customer_quotes SET status = ?, updated_at = ? WHERE id = ?",
                (status, datetime.now(timezone.utc).isoformat(), quote_id),
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
        if self._postgres:
            return self._postgres.record_automation_event(
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                status=status,
                result=result,
                error=error,
                idempotency_key=idempotency_key,
                attempts=attempts,
                max_attempts=max_attempts,
            )
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
        if self._postgres:
            return self._postgres.update_automation_event(
                event_id, status=status, attempts=attempts, result=result, error=error
            )
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE automation_events SET status = ?, attempts = ?, execution_time = ?, result = ?, error = ? WHERE id = ?",
                (status, attempts, datetime.now(timezone.utc).isoformat(), result, error, event_id),
            )
            conn.commit()
        finally:
            conn.close()

    def claim_automation_events(self, *, event_type: str, limit: int = 10) -> list[dict[str, Any]]:
        if self._postgres:
            return self._postgres.claim_automation_events(event_type=event_type, limit=limit)
        claimed = []
        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT id, attempts, max_attempts, entity_id, result FROM automation_events "
                "WHERE event_type = ? AND status = 'QUEUED' AND attempts < max_attempts "
                "ORDER BY created_at LIMIT ?",
                (event_type, min(max(int(limit), 1), 100)),
            ).fetchall()
            for row in rows:
                attempts = int(row["attempts"]) + 1
                cursor = conn.execute(
                    "UPDATE automation_events SET status = 'RUNNING', attempts = ?, execution_time = ? WHERE id = ? AND status = 'QUEUED'",
                    (attempts, datetime.now(timezone.utc).isoformat(), row["id"]),
                )
                if cursor.rowcount:
                    claimed.append({**dict(row), "attempts": attempts})
        return claimed

    def claim_carrier_webhook_event(self, event_id: str) -> bool:
        if self._postgres:
            return self._postgres.claim_carrier_webhook_event(event_id)
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
        if self._postgres:
            return self._postgres.list_automation_events(status=status, limit=limit)
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

    def get_automation_event(self, event_id: str) -> dict[str, Any] | None:
        if self._postgres:
            return self._postgres.get_automation_event(event_id)
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM automation_events WHERE id = ?", (event_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def enqueue_operator_review(
        self,
        *,
        idempotency_key: str,
        task: str,
        source_text: str,
        extraction: Dict[str, Any],
        reason: str,
        prompt_version: str | None = None,
        hold_flags: list[str] | None = None,
        entity_id: str | None = None,
    ) -> str:
        if self._postgres:
            return self._postgres.enqueue_operator_review(
                idempotency_key=idempotency_key,
                task=task,
                source_text=source_text,
                extraction=extraction,
                reason=reason,
                prompt_version=prompt_version,
                hold_flags=hold_flags,
                entity_id=entity_id,
            )
        now = datetime.now(timezone.utc).isoformat()
        review_id = f"REV-{uuid.uuid4().hex[:12].upper()}"
        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT id FROM operator_review_queue WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE operator_review_queue SET entity_id = COALESCE(?, entity_id), "
                    "source_text = ?, extraction_json = ?, reason = ?, prompt_version = COALESCE(?, prompt_version), "
                    "hold_flags_json = ?, updated_at = ? "
                    "WHERE id = ? AND status = 'PENDING'",
                    (entity_id, source_text, json.dumps(extraction), reason, prompt_version, json.dumps(hold_flags or []), now, existing[0]),
                )
                return str(existing[0])
            conn.execute(
                "INSERT INTO operator_review_queue "
                "(id, idempotency_key, task, prompt_version, entity_id, source_text, extraction_json, reason, hold_flags_json, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)",
                (review_id, idempotency_key, task, prompt_version, entity_id, source_text, json.dumps(extraction), reason,
                 json.dumps(hold_flags or []), now, now),
            )
        return review_id

    def get_operator_review(self, review_id: str) -> dict[str, Any] | None:
        if self._postgres:
            return self._postgres.get_operator_review(review_id)
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM operator_review_queue WHERE id = ?", (review_id,)).fetchone()
            return self._decode_operator_review(dict(row)) if row else None
        finally:
            conn.close()

    def list_operator_reviews(self, *, status: str = "PENDING", limit: int = 100) -> list[dict[str, Any]]:
        if self._postgres:
            return self._postgres.list_operator_reviews(status=status, limit=limit)
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM operator_review_queue WHERE status = ? ORDER BY created_at ASC LIMIT ?",
                (status, min(max(limit, 1), 500)),
            ).fetchall()
            return [self._decode_operator_review(dict(row)) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def _decode_operator_review(row: dict[str, Any]) -> dict[str, Any]:
        for column, key in (("extraction_json", "extraction"), ("hold_flags_json", "hold_flags"), ("decision_payload", "decision_payload")):
            raw = row.pop(column, None)
            row[key] = json.loads(raw) if raw else (None if key == "decision_payload" else {} if key == "extraction" else [])
        return row

    def link_operator_review_entity(self, review_id: str, entity_id: str) -> bool:
        if self._postgres:
            return self._postgres.link_operator_review_entity(review_id, entity_id)
        with self.transaction() as conn:
            cursor = conn.execute(
                "UPDATE operator_review_queue SET entity_id = ?, updated_at = ? WHERE id = ? AND status = 'PENDING'",
                (entity_id, datetime.now(timezone.utc).isoformat(), review_id),
            )
            return cursor.rowcount == 1

    def add_operator_review_flags(
        self,
        review_id: str,
        *,
        hold_flags: list[str],
        reason: str | None = None,
        entity_id: str | None = None,
    ) -> bool:
        if self._postgres:
            return self._postgres.add_operator_review_flags(
                review_id, hold_flags=hold_flags, reason=reason, entity_id=entity_id
            )
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT hold_flags_json, reason FROM operator_review_queue WHERE id = ? AND status = 'PENDING'",
                (review_id,),
            ).fetchone()
            if not row:
                return False
            merged_flags = sorted(set(json.loads(row[0] or "[]")) | set(hold_flags))
            merged_reason = "; ".join(dict.fromkeys(filter(None, [row[1], reason])))
            cursor = conn.execute(
                "UPDATE operator_review_queue SET hold_flags_json = ?, reason = ?, "
                "entity_id = COALESCE(?, entity_id), updated_at = ? WHERE id = ? AND status = 'PENDING'",
                (json.dumps(merged_flags), merged_reason, entity_id, datetime.now(timezone.utc).isoformat(), review_id),
            )
            return cursor.rowcount == 1

    def claim_operator_review_decision(self, review_id: str, decision: str, operator: str, payload: Dict[str, Any]) -> bool:
        if self._postgres:
            return self._postgres.claim_operator_review_decision(review_id, decision, operator, payload)
        if decision not in {"APPROVE", "REJECT"}:
            raise ValueError("Review decision must be APPROVE or REJECT.")
        with self.transaction() as conn:
            cursor = conn.execute(
                "UPDATE operator_review_queue SET status = 'PROCESSING', decision = ?, decision_by = ?, "
                "decision_payload = ?, updated_at = ? WHERE id = ? AND status = 'PENDING'",
                (decision, operator, json.dumps(payload), datetime.now(timezone.utc).isoformat(), review_id),
            )
            return cursor.rowcount == 1

    def complete_operator_review_decision(self, review_id: str, *, status: str, error: str | None = None) -> None:
        if self._postgres:
            return self._postgres.complete_operator_review_decision(review_id, status=status, error=error)
        if status not in {"APPROVED", "REJECTED", "PENDING"}:
            raise ValueError("Invalid operator review status.")
        with self.transaction() as conn:
            conn.execute(
                "UPDATE operator_review_queue SET status = ?, error = ?, "
                "decision = CASE WHEN ? = 'PENDING' THEN NULL ELSE decision END, "
                "decision_by = CASE WHEN ? = 'PENDING' THEN NULL ELSE decision_by END, "
                "decision_payload = CASE WHEN ? = 'PENDING' THEN NULL ELSE decision_payload END, updated_at = ? "
                "WHERE id = ? AND status IN ('PROCESSING', 'PENDING')",
                (status, error, status, status, status, datetime.now(timezone.utc).isoformat(), review_id),
            )
            if status in {"APPROVED", "REJECTED"}:
                conn.execute(
                    "UPDATE llm_telemetry SET operator_review_outcome = ? WHERE review_queue_id = ?",
                    (status, review_id),
                )

    def record_llm_telemetry(
        self,
        *,
        task: str,
        prompt_version: str,
        model_id: str,
        model_calls: list[str],
        latency_ms: float,
        input_tokens: int,
        output_tokens: int,
        estimated_cost_usd: float,
        validation_result: str,
        review_queue_id: str | None = None,
    ) -> str:
        if self._postgres:
            return self._postgres.record_llm_telemetry(
                task=task,
                prompt_version=prompt_version,
                model_id=model_id,
                model_calls=model_calls,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=estimated_cost_usd,
                validation_result=validation_result,
                review_queue_id=review_queue_id,
            )
        telemetry_id = f"LLM-{uuid.uuid4().hex[:12].upper()}"
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO llm_telemetry "
                "(id, task, prompt_version, model_id, model_calls_json, latency_ms, input_tokens, output_tokens, "
                "estimated_cost_usd, validation_result, review_queue_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    telemetry_id,
                    task,
                    prompt_version,
                    model_id,
                    json.dumps(model_calls),
                    max(float(latency_ms), 0.0),
                    max(int(input_tokens), 0),
                    max(int(output_tokens), 0),
                    max(float(estimated_cost_usd), 0.0),
                    validation_result,
                    review_queue_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return telemetry_id

    def list_llm_telemetry(self, *, task: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if self._postgres:
            return self._postgres.list_llm_telemetry(task=task, limit=limit)
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            bounded_limit = min(max(int(limit), 1), 500)
            if task:
                rows = conn.execute(
                    "SELECT * FROM llm_telemetry WHERE task = ? ORDER BY created_at DESC LIMIT ?",
                    (task, bounded_limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM llm_telemetry ORDER BY created_at DESC LIMIT ?",
                    (bounded_limit,),
                ).fetchall()
            results = [dict(row) for row in rows]
            for result in results:
                result["model_calls"] = json.loads(result.pop("model_calls_json"))
            return results
        finally:
            conn.close()


operations_store = OperationsStore()
