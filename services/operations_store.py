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
        production = (
            os.getenv("ENVIRONMENT", os.getenv("WT_ENV", "development")).strip().lower() == "production"
            or os.getenv("RENDER", "false").strip().lower() in {"1", "true", "yes", "on"}
        )
        if production and not os.getenv("DATABASE_URL", "").strip():
            raise RuntimeError("DATABASE_URL is required for production operational persistence.")
        if production:
            raise RuntimeError(
                "PostgreSQL operational repositories are not wired into OperationsStore; "
                "refusing to use SQLite for production business state."
            )
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
            conn.commit()
        finally:
            conn.close()

    @property
    def storage_engine(self) -> str:
        return "sqlite"

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
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM operator_review_queue WHERE id = ?", (review_id,)).fetchone()
            return self._decode_operator_review(dict(row)) if row else None
        finally:
            conn.close()

    def list_operator_reviews(self, *, status: str = "PENDING", limit: int = 100) -> list[dict[str, Any]]:
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
