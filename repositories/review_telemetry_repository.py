"""Synchronous PostgreSQL persistence for operator review and LLM telemetry."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def _sync_database_url(database_url: str) -> str:
    url = database_url.strip()
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    raise ValueError("DATABASE_URL must use a PostgreSQL URL scheme.")


class PostgresReviewTelemetryRepository:
    """PostgreSQL-backed records used by extraction and operator review only."""

    def __init__(self, database_url: str | None = None, *, engine: Engine | None = None):
        if engine is not None:
            self.engine = engine
            return
        configured_url = database_url or os.getenv("DATABASE_URL", "")
        if not configured_url.strip():
            raise RuntimeError("DATABASE_URL is required for PostgreSQL review persistence.")
        self.engine = create_engine(
            _sync_database_url(configured_url),
            pool_pre_ping=True,
            pool_recycle=1800,
        )

    @property
    def storage_engine(self) -> str:
        return "postgresql"

    def load_operations_state(self) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            value = connection.execute(text(
                "SELECT payload FROM operations_state WHERE state_key = 'current'"
            )).scalar_one_or_none()
            return json.loads(value) if value else None

    def save_operations_state(self, state: dict[str, Any]) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO operations_state (state_key, payload) VALUES ('current', :payload) "
                "ON CONFLICT (state_key) DO UPDATE SET payload = EXCLUDED.payload"
            ), {"payload": json.dumps(state, separators=(",", ":"))})

    def clear_operations_state(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("DELETE FROM operations_state WHERE state_key = 'current'"))

    def _one(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        value = dict(row)
        value["extraction"] = json.loads(value.pop("extraction_json"))
        value["hold_flags"] = json.loads(value.pop("hold_flags_json") or "[]")
        raw_decision = value.pop("decision_payload_json", None)
        value["decision_payload"] = json.loads(raw_decision) if raw_decision else None
        return value

    def enqueue_operator_review(
        self,
        *,
        idempotency_key: str,
        task: str,
        source_text: str,
        extraction: dict[str, Any],
        reason: str,
        prompt_version: str | None = None,
        hold_flags: list[str] | None = None,
        entity_id: str | None = None,
    ) -> str:
        review_id = f"REV-{uuid.uuid4().hex[:12].upper()}"
        with self.engine.begin() as connection:
            row = connection.execute(text(
                "INSERT INTO operator_review_queue "
                "(id, idempotency_key, task, prompt_version, entity_id, source_text, extraction_json, reason, "
                "hold_flags_json, status, created_at, updated_at) "
                "VALUES (:id, :key, :task, :prompt_version, :entity, :source, :extraction, :reason, :flags, "
                "'PENDING', now(), now()) ON CONFLICT (idempotency_key) DO UPDATE SET "
                "entity_id = COALESCE(EXCLUDED.entity_id, operator_review_queue.entity_id), "
                "source_text = EXCLUDED.source_text, extraction_json = EXCLUDED.extraction_json, "
                "reason = EXCLUDED.reason, prompt_version = COALESCE(EXCLUDED.prompt_version, operator_review_queue.prompt_version), "
                "hold_flags_json = EXCLUDED.hold_flags_json, updated_at = now() "
                "WHERE operator_review_queue.status = 'PENDING' "
                "RETURNING id"
            ), {
                "id": review_id,
                "key": idempotency_key,
                "task": task,
                "prompt_version": prompt_version,
                "entity": entity_id,
                "source": source_text,
                "extraction": json.dumps(extraction),
                "reason": reason,
                "flags": json.dumps(hold_flags or []),
            }).first()
            if row:
                return str(row[0])
            existing = connection.execute(text(
                "SELECT id FROM operator_review_queue WHERE idempotency_key = :key"
            ), {"key": idempotency_key}).scalar_one_or_none()
            if existing:
                return str(existing)
            raise RuntimeError("Operator review could not be inserted or found after idempotency conflict.")

    def get_operator_review(self, review_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(text(
                "SELECT id, idempotency_key, task, prompt_version, entity_id, source_text, extraction_json, reason, "
                "hold_flags_json, status, decision, decision_by, decision_payload AS decision_payload_json, error, "
                "created_at, updated_at FROM operator_review_queue WHERE id = :id"
            ), {"id": review_id}).mappings().first()
            return self._one(row)

    def list_operator_reviews(self, *, status: str = "PENDING", limit: int = 100) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT id, idempotency_key, task, prompt_version, entity_id, source_text, extraction_json, reason, "
                "hold_flags_json, status, decision, decision_by, decision_payload AS decision_payload_json, error, "
                "created_at, updated_at FROM operator_review_queue WHERE status = :status "
                "ORDER BY created_at ASC LIMIT :limit"
            ), {"status": status, "limit": min(max(int(limit), 1), 500)}).mappings().all()
            return [self._one(row) for row in rows]

    def link_operator_review_entity(self, review_id: str, entity_id: str) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(text(
                "UPDATE operator_review_queue SET entity_id = :entity, updated_at = now() "
                "WHERE id = :id AND status = 'PENDING'"
            ), {"entity": entity_id, "id": review_id})
            return result.rowcount == 1

    def add_operator_review_flags(
        self,
        review_id: str,
        *,
        hold_flags: list[str],
        reason: str | None = None,
        entity_id: str | None = None,
    ) -> bool:
        with self.engine.begin() as connection:
            row = connection.execute(text(
                "SELECT hold_flags_json, reason FROM operator_review_queue WHERE id = :id AND status = 'PENDING' FOR UPDATE"
            ), {"id": review_id}).first()
            if not row:
                return False
            flags = sorted(set(json.loads(row[0] or "[]")) | set(hold_flags))
            combined_reason = "; ".join(dict.fromkeys(filter(None, [row[1], reason])))
            result = connection.execute(text(
                "UPDATE operator_review_queue SET hold_flags_json = :flags, reason = :reason, "
                "entity_id = COALESCE(:entity, entity_id), updated_at = now() WHERE id = :id AND status = 'PENDING'"
            ), {"flags": json.dumps(flags), "reason": combined_reason, "entity": entity_id, "id": review_id})
            return result.rowcount == 1

    def claim_operator_review_decision(self, review_id: str, decision: str, operator: str, payload: dict[str, Any]) -> bool:
        decision = decision.upper()
        if decision not in {"APPROVE", "REJECT"}:
            raise ValueError("Review decision must be APPROVE or REJECT.")
        with self.engine.begin() as connection:
            result = connection.execute(text(
                "UPDATE operator_review_queue SET status = 'PROCESSING', decision = :decision, decision_by = :operator, "
                "decision_payload = :payload, updated_at = now() WHERE id = :id AND status = 'PENDING'"
            ), {"decision": decision, "operator": operator, "payload": json.dumps(payload), "id": review_id})
            return result.rowcount == 1

    def complete_operator_review_decision(self, review_id: str, *, status: str, error: str | None = None) -> None:
        if status not in {"APPROVED", "REJECTED", "PENDING"}:
            raise ValueError("Invalid operator review status.")
        with self.engine.begin() as connection:
            connection.execute(text(
                "UPDATE operator_review_queue SET status = :status, error = :error, "
                "decision = CASE WHEN :status = 'PENDING' THEN NULL ELSE decision END, "
                "decision_by = CASE WHEN :status = 'PENDING' THEN NULL ELSE decision_by END, "
                "decision_payload = CASE WHEN :status = 'PENDING' THEN NULL ELSE decision_payload END, "
                "updated_at = now() WHERE id = :id AND status IN ('PROCESSING', 'PENDING')"
            ), {"status": status, "error": error, "id": review_id})
            if status in {"APPROVED", "REJECTED"}:
                connection.execute(text(
                    "UPDATE llm_telemetry SET operator_review_outcome = :status WHERE review_queue_id = :id"
                ), {"status": status, "id": review_id})

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
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO llm_telemetry (id, task, prompt_version, model_id, model_calls_json, latency_ms, "
                "input_tokens, output_tokens, estimated_cost_usd, validation_result, review_queue_id, created_at) "
                "VALUES (:id, :task, :prompt, :model, :calls, :latency, :input_tokens, :output_tokens, :cost, "
                ":validation, :review_id, now())"
            ), {
                "id": telemetry_id,
                "task": task,
                "prompt": prompt_version,
                "model": model_id,
                "calls": json.dumps(model_calls),
                "latency": max(float(latency_ms), 0.0),
                "input_tokens": max(int(input_tokens), 0),
                "output_tokens": max(int(output_tokens), 0),
                "cost": max(float(estimated_cost_usd), 0.0),
                "validation": validation_result,
                "review_id": review_queue_id,
            })
        return telemetry_id

    def list_llm_telemetry(self, *, task: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        clause = "WHERE task = :task" if task else ""
        parameters = {"limit": min(max(int(limit), 1), 500)}
        if task:
            parameters["task"] = task
        with self.engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT id, task, prompt_version, model_id, model_calls_json, latency_ms, input_tokens, "
                "output_tokens, estimated_cost_usd, validation_result, operator_review_outcome, review_queue_id, created_at "
                f"FROM llm_telemetry {clause} ORDER BY created_at DESC LIMIT :limit"
            ), parameters).mappings().all()
            return [{**dict(row), "model_calls": json.loads(row["model_calls_json"])} for row in rows]

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
        event_id = f"AUT-{uuid.uuid4().hex[:12].upper()}"
        with self.engine.begin() as connection:
            row = connection.execute(text(
                "INSERT INTO automation_events (id, idempotency_key, event_type, entity_type, entity_id, status, "
                "attempts, max_attempts, execution_time, result, error, created_at) VALUES "
                "(:id, :key, :type, :entity_type, :entity, :status, :attempts, :max_attempts, now(), :result, :error, now()) "
                "ON CONFLICT (idempotency_key) DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key RETURNING id"
            ), {
                "id": event_id, "key": idempotency_key, "type": event_type, "entity_type": entity_type,
                "entity": entity_id, "status": status, "attempts": attempts, "max_attempts": max_attempts,
                "result": result, "error": error,
            }).scalar_one()
        return str(row)

    def update_automation_event(self, event_id: str, *, status: str, attempts: int, result: str | None = None, error: str | None = None) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(
                "UPDATE automation_events SET status = :status, attempts = :attempts, execution_time = now(), "
                "result = :result, error = :error WHERE id = :id"
            ), {"status": status, "attempts": attempts, "result": result, "error": error, "id": event_id})

    def list_automation_events(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        clause = "WHERE status = :status" if status else ""
        parameters = {"limit": min(max(int(limit), 1), 500)}
        if status:
            parameters["status"] = status
        with self.engine.connect() as connection:
            rows = connection.execute(text(
                f"SELECT * FROM automation_events {clause} ORDER BY created_at DESC LIMIT :limit"
            ), parameters).mappings().all()
            return [dict(row) for row in rows]

    def get_automation_event(self, event_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(text(
                "SELECT * FROM automation_events WHERE id = :id"
            ), {"id": event_id}).mappings().first()
            return dict(row) if row else None

    def claim_carrier_webhook_event(self, event_id: str) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(text(
                "INSERT INTO carrier_webhook_events (event_id, received_at) VALUES (:id, now()) "
                "ON CONFLICT (event_id) DO NOTHING"
            ), {"id": event_id})
            return result.rowcount == 1
