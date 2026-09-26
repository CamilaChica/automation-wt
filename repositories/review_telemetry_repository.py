"""Synchronous PostgreSQL persistence for operator review and LLM telemetry."""

from __future__ import annotations

import json
import os
import socket
import threading
import uuid
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlsplit

from models.operational_models import InboundEmailRecord, OperationalRecord, SupplierPartRecord, SupplierRecord
from schemas.supplier import SupplierOfferEntry, SupplierRegistryEntry
from sqlalchemy import create_engine, inspect, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine


def _sync_database_url(database_url: str) -> str:
    url = database_url.strip()
    fallback = os.getenv("DATABASE_URL_FALLBACK", "").strip()
    host = urlsplit(url.replace("postgresql+asyncpg://", "postgresql://", 1)).hostname
    if fallback and host:
        try:
            socket.getaddrinfo(host, None)
        except socket.gaierror:
            url = fallback
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    raise ValueError("DATABASE_URL must use a PostgreSQL URL scheme.")


class PostgresReviewTelemetryRepository:
    """Synchronous PostgreSQL adapter for the OperationsStore contract."""

    def __init__(self, database_url: str | None = None, *, engine: Engine | None = None):
        self._transaction_state = threading.local()
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

    def check_operational_schema(self) -> dict[str, Any]:
        required = {
            "customers", "rfqs", "rfq_items", "supplier_offers", "quotes", "quote_items",
            "communications", "audit_events", "workflow_state", "communication_tasks",
            "inbound_message_idempotency", "agent_handoffs", "operator_review_queue",
            "llm_telemetry", "automation_events", "carrier_webhook_events", "operations_state",
            "customer_quotes", "customer_quote_items", "operational_records", "suppliers",
            "supplier_parts", "outbox_messages", "inbound_emails",
        }
        with self._read() as connection:
            existing = set(inspect(connection).get_table_names())
        missing = sorted(required - existing)
        return {"ready": not missing, "missing_tables": missing}

    def load_operations_state(self) -> dict[str, Any] | None:
        with self._read() as connection:
            value = connection.execute(text(
                "SELECT payload FROM operations_state WHERE state_key = 'current'"
            )).scalar_one_or_none()
            return json.loads(value) if value else None

    def save_operations_state(self, state: dict[str, Any]) -> None:
        with self._begin() as connection:
            connection.execute(text(
                "INSERT INTO operations_state (state_key, payload) VALUES ('current', :payload) "
                "ON CONFLICT (state_key) DO UPDATE SET payload = EXCLUDED.payload"
            ), {"payload": json.dumps(state, separators=(",", ":"))})

    def clear_operations_state(self) -> None:
        with self._begin() as connection:
            connection.execute(text("DELETE FROM operations_state WHERE state_key = 'current'"))

    def get_operational_record(self, domain: str, record_id: str) -> dict[str, Any] | None:
        with self._read() as connection:
            row = connection.execute(text(
                "SELECT payload FROM operational_records WHERE domain = :domain AND record_id = :record_id"
            ), {"domain": domain, "record_id": record_id}).scalar_one_or_none()
            return dict(row) if row is not None else None

    def lock_operational_record(self, domain: str, record_id: str) -> dict[str, Any] | None:
        with self._begin() as connection:
            row = connection.execute(
                select(OperationalRecord.payload)
                .where(OperationalRecord.domain == domain, OperationalRecord.record_id == record_id)
                .with_for_update()
            ).scalar_one_or_none()
            return dict(row) if row is not None else None

    def list_operational_records(self, domain: str) -> dict[str, dict[str, Any]]:
        with self._read() as connection:
            rows = connection.execute(text(
                "SELECT record_id, payload FROM operational_records WHERE domain = :domain"
            ), {"domain": domain}).all()
            return {str(row[0]): dict(row[1]) for row in rows}

    def save_operational_record(self, domain: str, record_id: str, payload: dict[str, Any]) -> None:
        with self._begin() as connection:
            connection.execute(
                insert(OperationalRecord)
                .values(domain=domain, record_id=record_id, payload=payload)
                .on_conflict_do_update(
                    index_elements=["domain", "record_id"],
                    set_={"payload": payload, "updated_at": text("now()")},
                )
            )

    def delete_operational_record(self, domain: str, record_id: str) -> None:
        with self._begin() as connection:
            connection.execute(text(
                "DELETE FROM operational_records WHERE domain = :domain AND record_id = :record_id"
            ), {"domain": domain, "record_id": record_id})

    def reserve_inventory(self, part_number: str, quantity: int) -> bool:
        if quantity < 1:
            raise ValueError("Reservation quantity must be positive.")
        with self._begin() as connection:
            rows = connection.execute(
                select(OperationalRecord.record_id, OperationalRecord.payload)
                .where(OperationalRecord.domain == "inventory")
                .with_for_update()
            ).all()
            matching = sorted(
                ((str(record_id), dict(payload)) for record_id, payload in rows
                 if str(payload.get("part_number", "")).upper() == part_number.upper()),
                key=lambda row: row[0],
            )
            if sum(int(payload.get("quantity_available", 0)) for _, payload in matching) < quantity:
                return False
            remaining = quantity
            for record_id, payload in matching:
                allocation = min(int(payload.get("quantity_available", 0)), remaining)
                payload["quantity_available"] = int(payload.get("quantity_available", 0)) - allocation
                connection.execute(
                    update(OperationalRecord)
                    .where(OperationalRecord.domain == "inventory", OperationalRecord.record_id == record_id)
                    .values(payload=payload, updated_at=text("now()"))
                )
                remaining -= allocation
                if remaining == 0:
                    break
            return True

    def claim_inbound_message(self, message_id: str, mailbox: str) -> bool:
        with self._begin() as connection:
            result = connection.execute(text(
                "INSERT INTO inbound_message_idempotency (message_id, mailbox, processed_at, status) "
                "VALUES (:message_id, :mailbox, now(), 'processing') "
                "ON CONFLICT (message_id) DO NOTHING RETURNING message_id"
            ), {"message_id": message_id, "mailbox": mailbox})
            return result.scalar_one_or_none() is not None

    def mark_inbound_message_processed(self, message_id: str) -> None:
        with self._begin() as connection:
            connection.execute(text(
                "UPDATE inbound_message_idempotency SET status = 'processed', processed_at = now() "
                "WHERE message_id = :message_id"
            ), {"message_id": message_id})

    def save_inbound_email(self, *, mailbox: str, message_id: str, sender: str, subject: str, body: str, processing_status: str = "processed") -> str:
        email_id = f"EML-{uuid.uuid5(uuid.NAMESPACE_URL, message_id).hex[:16].upper()}"
        with self._begin() as connection:
            result = connection.execute(insert(InboundEmailRecord).values(
                id=email_id, mailbox=mailbox, message_id=message_id, sender=sender,
                subject=subject, body=body, processing_status=processing_status,
            ).on_conflict_do_update(
                index_elements=[InboundEmailRecord.message_id],
                set_={"mailbox": mailbox, "sender": sender, "subject": subject, "body": body,
                      "processing_status": processing_status},
            ).returning(InboundEmailRecord.id))
            return str(result.scalar_one())

    def release_inbound_message(self, message_id: str) -> None:
        with self._begin() as connection:
            connection.execute(text(
                "DELETE FROM inbound_message_idempotency WHERE message_id = :message_id AND status = 'processing'"
            ), {"message_id": message_id})

    @contextmanager
    def transaction(self):
        active = getattr(self._transaction_state, "connection", None)
        if active is not None:
            yield active
            return
        with self.engine.begin() as connection:
            self._transaction_state.connection = connection
            try:
                yield connection
            finally:
                del self._transaction_state.connection

    @contextmanager
    def _begin(self):
        active = getattr(self._transaction_state, "connection", None)
        if active is not None:
            yield active
            return
        with self.engine.begin() as connection:
            yield connection

    @contextmanager
    def _read(self):
        active = getattr(self._transaction_state, "connection", None)
        if active is not None:
            yield active
            return
        with self.engine.connect() as connection:
            yield connection

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
        with self._begin() as connection:
            connection.execute(text(
                "INSERT INTO communications "
                "(id, entity_type, entity_id, recipient, sender, channel, subject, message, "
                "message_type, status, sent_at, response_received, created_at) "
                "VALUES (:id, :entity_type, :entity_id, :recipient, :sender, :channel, :subject, :message, "
                ":message_type, :status, CASE WHEN :status = 'SENT' THEN now() ELSE NULL END, :response, now())"
            ), {
                "id": communication_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "recipient": recipient,
                "sender": sender,
                "channel": channel,
                "subject": subject or "",
                "message": message or "",
                "message_type": message_type,
                "status": status,
                "response": response_received,
            })
        return communication_id

    def upsert_customer(self, customer_id: str, company_name: str, contact_name: str, email: str) -> None:
        with self._begin() as connection:
            connection.execute(text(
                "INSERT INTO customers (id, company_name, contact_name, email, created_at, updated_at) "
                "VALUES (:id, :company, :contact, :email, now(), now()) "
                "ON CONFLICT (id) DO UPDATE SET company_name = EXCLUDED.company_name, "
                "contact_name = EXCLUDED.contact_name, email = EXCLUDED.email, updated_at = now()"
            ), {"id": customer_id, "company": company_name, "contact": contact_name, "email": email})

    def insert_rfq(
        self,
        *,
        rfq_id: str,
        customer_id: str,
        part_number: str | None,
        description: str,
        quantity: int,
        condition: str | None,
        certification: str | None,
        destination: str | None,
        status: str,
        raw_text: str,
        thread_id: str | None,
    ) -> None:
        with self._begin() as connection:
            customer = connection.execute(text(
                "SELECT email, company_name FROM customers WHERE id = :customer_id"
            ), {"customer_id": customer_id}).mappings().first()
            if customer is None:
                raise ValueError(f"Customer {customer_id} must exist before its RFQ is inserted.")
            connection.execute(text(
                "INSERT INTO rfqs (id, customer_id, customer_email, customer_name, part_number, description, quantity, "
                "condition_requested, certification_requested, destination, status, raw_text, thread_id, created_at, updated_at) "
                "VALUES (:id, :customer_id, :email, :customer_name, :part_number, :description, :quantity, :condition, "
                ":certification, :destination, :status, :raw_text, :thread_id, now(), now()) "
                "ON CONFLICT (id) DO UPDATE SET customer_id = EXCLUDED.customer_id, customer_email = EXCLUDED.customer_email, "
                "customer_name = EXCLUDED.customer_name, part_number = COALESCE(EXCLUDED.part_number, rfqs.part_number), "
                "description = COALESCE(EXCLUDED.description, rfqs.description), quantity = EXCLUDED.quantity, "
                "condition_requested = COALESCE(EXCLUDED.condition_requested, rfqs.condition_requested), "
                "certification_requested = COALESCE(EXCLUDED.certification_requested, rfqs.certification_requested), "
                "destination = COALESCE(EXCLUDED.destination, rfqs.destination), status = EXCLUDED.status, "
                "raw_text = COALESCE(EXCLUDED.raw_text, rfqs.raw_text), thread_id = COALESCE(EXCLUDED.thread_id, rfqs.thread_id), "
                "updated_at = now()"
            ), {
                "id": rfq_id,
                "customer_id": customer_id,
                "email": customer["email"],
                "customer_name": customer["company_name"],
                "part_number": part_number,
                "description": description,
                "quantity": quantity,
                "condition": condition,
                "certification": certification,
                "destination": destination,
                "status": status,
                "raw_text": raw_text,
                "thread_id": thread_id,
            })

    def update_rfq_status(self, rfq_id: str, status: str) -> None:
        with self._begin() as connection:
            connection.execute(text(
                "UPDATE rfqs SET status = :status, updated_at = now() WHERE id = :id"
            ), {"status": status, "id": rfq_id})

    def insert_customer_quote(
        self,
        *,
        quote_id: str,
        rfq_id: str,
        unit_price: float,
        quantity: int,
        total_price: float,
        lead_time: int | None,
        condition: str | None,
        certification: str | None,
        valid_until: str | None,
        status: str,
    ) -> None:
        with self._begin() as connection:
            connection.execute(text(
                "INSERT INTO customer_quotes (id, rfq_id, quote_number, unit_price, quantity, total_price, currency, "
                "lead_time, condition, certification, valid_until, status, created_at, updated_at) "
                "VALUES (:id, :rfq_id, :number, :unit_price, :quantity, :total, 'USD', :lead_time, :condition, "
                ":certification, :valid_until, :status, now(), now()) "
                "ON CONFLICT (id) DO UPDATE SET unit_price = EXCLUDED.unit_price, quantity = EXCLUDED.quantity, "
                "total_price = EXCLUDED.total_price, lead_time = EXCLUDED.lead_time, condition = EXCLUDED.condition, "
                "certification = EXCLUDED.certification, valid_until = EXCLUDED.valid_until, status = EXCLUDED.status, updated_at = now()"
            ), {
                "id": quote_id,
                "rfq_id": rfq_id,
                "number": quote_id,
                "unit_price": unit_price,
                "quantity": quantity,
                "total": total_price,
                "lead_time": lead_time,
                "condition": condition,
                "certification": certification,
                "valid_until": valid_until,
                "status": status,
            })

    def insert_customer_quote_item(
        self,
        *,
        item_id: str,
        quote_id: str,
        rfq_item_id: str,
        part_number: str,
        description: str,
        quantity: int,
        condition: str | None,
        certification: str,
        unit_price: float,
        lead_time: int | None,
        attachments: str = "",
    ) -> None:
        with self._begin() as connection:
            connection.execute(text(
                "INSERT INTO customer_quote_items (id, quote_id, rfq_item_id, part_number, description, quantity, "
                "condition, certification, unit_price, lead_time, attachments, created_at, updated_at) "
                "VALUES (:id, :quote_id, :rfq_item_id, :part_number, :description, :quantity, :condition, "
                ":certification, :unit_price, :lead_time, :attachments, now(), now()) "
                "ON CONFLICT (id) DO UPDATE SET description = EXCLUDED.description, quantity = EXCLUDED.quantity, "
                "condition = EXCLUDED.condition, certification = EXCLUDED.certification, unit_price = EXCLUDED.unit_price, "
                "lead_time = EXCLUDED.lead_time, attachments = EXCLUDED.attachments, updated_at = now()"
            ), {
                "id": item_id,
                "quote_id": quote_id,
                "rfq_item_id": rfq_item_id,
                "part_number": part_number,
                "description": description,
                "quantity": quantity,
                "condition": condition,
                "certification": certification,
                "unit_price": unit_price,
                "lead_time": lead_time,
                "attachments": attachments,
            })

    def update_customer_quote_status(self, quote_id: str, status: str) -> None:
        with self._begin() as connection:
            connection.execute(text(
                "UPDATE customer_quotes SET status = :status, updated_at = now() WHERE id = :id"
            ), {"status": status, "id": quote_id})

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
        with self._begin() as connection:
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
        with self._read() as connection:
            row = connection.execute(text(
                "SELECT id, idempotency_key, task, prompt_version, entity_id, source_text, extraction_json, reason, "
                "hold_flags_json, status, decision, decision_by, decision_payload AS decision_payload_json, error, "
                "created_at, updated_at FROM operator_review_queue WHERE id = :id"
            ), {"id": review_id}).mappings().first()
            return self._one(row)

    def list_operator_reviews(self, *, status: str = "PENDING", limit: int = 100) -> list[dict[str, Any]]:
        with self._read() as connection:
            rows = connection.execute(text(
                "SELECT id, idempotency_key, task, prompt_version, entity_id, source_text, extraction_json, reason, "
                "hold_flags_json, status, decision, decision_by, decision_payload AS decision_payload_json, error, "
                "created_at, updated_at FROM operator_review_queue WHERE status = :status "
                "ORDER BY created_at ASC LIMIT :limit"
            ), {"status": status, "limit": min(max(int(limit), 1), 500)}).mappings().all()
            return [self._one(row) for row in rows]

    def link_operator_review_entity(self, review_id: str, entity_id: str) -> bool:
        with self._begin() as connection:
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
        with self._begin() as connection:
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
        with self._begin() as connection:
            result = connection.execute(text(
                "UPDATE operator_review_queue SET status = 'PROCESSING', decision = :decision, decision_by = :operator, "
                "decision_payload = :payload, updated_at = now() WHERE id = :id AND status = 'PENDING'"
            ), {"decision": decision, "operator": operator, "payload": json.dumps(payload), "id": review_id})
            return result.rowcount == 1

    def complete_operator_review_decision(self, review_id: str, *, status: str, error: str | None = None) -> None:
        if status not in {"APPROVED", "REJECTED", "PENDING"}:
            raise ValueError("Invalid operator review status.")
        with self._begin() as connection:
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
        with self._begin() as connection:
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
        with self._read() as connection:
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
        with self._begin() as connection:
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
        with self._begin() as connection:
            connection.execute(text(
                "UPDATE automation_events SET status = :status, attempts = :attempts, execution_time = now(), "
                "result = :result, error = :error WHERE id = :id"
            ), {"status": status, "attempts": attempts, "result": result, "error": error, "id": event_id})

    def list_automation_events(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        clause = "WHERE status = :status" if status else ""
        parameters = {"limit": min(max(int(limit), 1), 500)}
        if status:
            parameters["status"] = status
        with self._read() as connection:
            rows = connection.execute(text(
                f"SELECT * FROM automation_events {clause} ORDER BY created_at DESC LIMIT :limit"
            ), parameters).mappings().all()
            return [dict(row) for row in rows]

    def get_automation_event(self, event_id: str) -> dict[str, Any] | None:
        with self._read() as connection:
            row = connection.execute(text(
                "SELECT * FROM automation_events WHERE id = :id"
            ), {"id": event_id}).mappings().first()
            return dict(row) if row else None

    def claim_carrier_webhook_event(self, event_id: str) -> bool:
        with self._begin() as connection:
            result = connection.execute(text(
                "INSERT INTO carrier_webhook_events (event_id, received_at) VALUES (:id, now()) "
                "ON CONFLICT (event_id) DO NOTHING"
            ), {"id": event_id})
            return result.rowcount == 1

    def enqueue_outbox_message(
        self,
        *,
        deduplication_key: str,
        mailbox: str,
        recipient: str,
        subject: str,
        body: str,
        reply_to: str | None = None,
        communication_task_id: str | None = None,
        entity_id: str | None = None,
        max_retries: int = 5,
    ) -> dict[str, Any]:
        message_id = f"OUT-{uuid.uuid4().hex[:16].upper()}"
        with self._begin() as connection:
            row = connection.execute(text(
                "INSERT INTO outbox_messages "
                "(id, deduplication_key, entity_id, mailbox, recipient, subject, payload, reply_to, communication_task_id, status, max_retries, available_at, created_at) "
                "VALUES (:id, :key, :entity_id, :mailbox, :recipient, :subject, CAST(:payload AS json), :reply_to, :task_id, 'PENDING', :max_retries, now(), now()) "
                "ON CONFLICT (deduplication_key) DO UPDATE SET deduplication_key = EXCLUDED.deduplication_key "
                "RETURNING id, status, retry_count, created_at"
            ), {
                "id": message_id,
                "key": deduplication_key,
                "entity_id": entity_id,
                "mailbox": mailbox,
                "recipient": recipient,
                "subject": subject,
                "payload": json.dumps({"body": body}),
                "reply_to": reply_to,
                "task_id": communication_task_id,
                "max_retries": max(1, int(max_retries)),
            }).mappings().one()
            return dict(row)

    def claim_outbox_messages(self, *, limit: int = 25) -> list[dict[str, Any]]:
        bounded_limit = min(max(int(limit), 1), 100)
        with self._begin() as connection:
            rows = connection.execute(text(
                "WITH candidates AS ("
                " SELECT id FROM outbox_messages WHERE status = 'PENDING' AND available_at <= now() "
                " ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT :limit"
                ") UPDATE outbox_messages AS outbox SET status = 'SENDING', retry_count = retry_count + 1, sending_started_at = now() "
                "FROM candidates WHERE outbox.id = candidates.id "
                "RETURNING outbox.id, outbox.deduplication_key, outbox.entity_id, outbox.mailbox, outbox.recipient, "
                "outbox.subject, outbox.payload, outbox.reply_to, outbox.retry_count, outbox.max_retries"
            ), {"limit": bounded_limit}).mappings().all()
            return [{**dict(row), "payload": row["payload"]} for row in rows]

    def mark_outbox_sent(self, message_id: str) -> None:
        with self._begin() as connection:
            task_id = connection.execute(text(
                "SELECT communication_task_id FROM outbox_messages WHERE id = :id FOR UPDATE"
            ), {"id": message_id}).scalar_one_or_none()
            connection.execute(text(
                "UPDATE outbox_messages SET status = 'SENT', sent_at = now(), sending_started_at = NULL, error_message = NULL "
                "WHERE id = :id AND status = 'SENDING'"
            ), {"id": message_id})
            if task_id:
                connection.execute(text(
                    "UPDATE communication_tasks SET status = 'sent', sent_at = now(), attempts = attempts + 1 "
                    "WHERE id = :task_id"
                ), {"task_id": task_id})

    def fail_outbox_message(self, message_id: str, error: str, *, retryable: bool = False) -> str:
        with self._begin() as connection:
            task_id = connection.execute(text(
                "SELECT communication_task_id FROM outbox_messages WHERE id = :id FOR UPDATE"
            ), {"id": message_id}).scalar_one_or_none()
            outbox_status = connection.execute(text(
                "UPDATE outbox_messages SET "
                "status = CASE WHEN :retryable AND retry_count < max_retries THEN 'PENDING' ELSE 'MANUAL_REVIEW_REQUIRED' END, "
                "error_message = :error, available_at = now() + LEAST(interval '1 hour', "
                "interval '5 seconds' * power(2, GREATEST(retry_count - 1, 0))), sending_started_at = NULL "
                "WHERE id = :id AND status = 'SENDING' RETURNING status"
            ), {"id": message_id, "error": str(error)[:2000], "retryable": bool(retryable)}).scalar_one_or_none()
            if task_id:
                connection.execute(text(
                    "UPDATE communication_tasks SET status = CASE WHEN :status = 'PENDING' THEN 'pending' ELSE 'manual_review_required' END, "
                    "attempts = attempts + 1, last_error = :error WHERE id = :task_id"
                ), {"task_id": task_id, "status": outbox_status or "MANUAL_REVIEW_REQUIRED", "error": str(error)[:1000]})
            return str(outbox_status or "MANUAL_REVIEW_REQUIRED")

    def recover_stale_outbox_messages(self, *, sending_timeout_seconds: int = 300) -> int:
        with self._begin() as connection:
            result = connection.execute(text(
                "WITH recovered AS (UPDATE outbox_messages SET status = 'MANUAL_REVIEW_REQUIRED', sending_started_at = NULL, "
                "error_message = 'Delivery outcome unknown after stale SENDING lease; manual verification required' "
                "WHERE status = 'SENDING' AND sending_started_at < now() - make_interval(secs => :timeout) "
                "RETURNING communication_task_id) UPDATE communication_tasks SET status = 'manual_review_required', "
                "last_error = 'Outbox delivery outcome unknown; manual verification required' "
                "WHERE id IN (SELECT communication_task_id FROM recovered WHERE communication_task_id IS NOT NULL)"
            ), {"timeout": max(1, int(sending_timeout_seconds))})
            return int(result.rowcount or 0)

    def upsert_supplier(self, supplier_name: str, supplier_email: str | None = None, phone: str | None = None, approval_status: str = "Pending") -> str:
        supplier_id = f"SUP-{uuid.uuid5(uuid.NAMESPACE_URL, (supplier_email or supplier_name).strip().lower()).hex[:16].upper()}"
        supplier_data = SupplierRegistryEntry(
            id=supplier_id, company_name=supplier_name, email=supplier_email,
            phone=phone, approval_status=approval_status,
        )
        with self._begin() as connection:
            existing = connection.execute(select(SupplierRecord.id).where(
                or_(SupplierRecord.company_name == supplier_name,
                    SupplierRecord.email == supplier_email if supplier_email else text("false"))
            ).limit(1)).scalar_one_or_none()
            supplier_id = str(existing or supplier_id)
            supplier_values = supplier_data.model_dump()
            connection.execute(insert(SupplierRecord).values(
                **supplier_values,
            ).on_conflict_do_update(index_elements=[SupplierRecord.id], set_={
                "company_name": supplier_name, "email": supplier_email, "phone": phone,
                "approval_status": approval_status, "updated_at": text("now()"),
            }))
            return supplier_id

    def list_suppliers(self) -> list[dict[str, Any]]:
        with self._read() as connection:
            rows = connection.execute(select(SupplierRecord).order_by(SupplierRecord.company_name)).scalars().all()
            return [{"id": row.id, "company_name": row.company_name, "email": row.email,
                     "phone": row.phone, "approval_status": row.approval_status,
                     "itar_certified": row.itar_certified} for row in rows]

    def save_supplier_offer(self, *, supplier_name: str, supplier_email: str | None = None, part_number: str = "", quantity_available: int | None = None, unit_cost: float | None = None, certificate_type: str | None = None, lead_time_days: int | None = None, approval_status: str = "Pending", condition_code: str | None = None, source_email_id: str | None = None, confidence: float = 1.0, description: str = "", availability_location: str | None = None, warranty_terms: str | None = None, trace_documents: list[str] | None = None, currency: str = "USD") -> dict[str, Any]:
        with self._begin() as connection:
            supplier_id = self.upsert_supplier(supplier_name, supplier_email, approval_status=approval_status)
            offer_id = (
                f"SPO-{uuid.uuid5(uuid.NAMESPACE_URL, source_email_id).hex[:24].upper()}"
                if source_email_id else f"SPO-{uuid.uuid4().hex[:24].upper()}"
            )
            normalized_part = part_number.strip().upper()
            trace_json = json.dumps(trace_documents or [])
            offer_data = SupplierOfferEntry(
                id=offer_id, supplier_id=supplier_id, part_number=normalized_part,
                condition_code=condition_code, description=description,
                quantity_available=quantity_available, unit_cost=unit_cost, currency=currency,
                certificate_type=certificate_type, lead_time_days=lead_time_days,
                availability_location=availability_location, warranty_terms=warranty_terms,
                source_email_id=source_email_id, confidence=confidence, approval_status=approval_status,
            )
            values = {**offer_data.model_dump(), "trace_documents": trace_json}
            statement = insert(SupplierPartRecord).values(**values)
            update_values = {key: value for key, value in values.items() if key not in {"id", "source_email_id"}}
            update_values["updated_at"] = text("now()")
            if source_email_id:
                statement = statement.on_conflict_do_update(index_elements=[SupplierPartRecord.source_email_id], set_=update_values)
            else:
                statement = statement.on_conflict_do_nothing(index_elements=[SupplierPartRecord.id])
            saved_id = connection.execute(statement.returning(SupplierPartRecord.id)).scalar_one_or_none()
            return {**values, "id": str(saved_id or offer_id), "supplier_name": supplier_name,
                    "supplier_email": supplier_email, "trace_documents": trace_documents or []}

    def get_supplier_offers(self, part_number: str, quantity_needed: int = 1) -> list[dict[str, Any]]:
        with self._read() as connection:
            rows = connection.execute(text(
                "SELECT p.id AS supplier_part_id, p.supplier_id, p.part_number, p.quantity_available, p.unit_cost, "
                "p.certificate_type, p.lead_time_days, p.condition_code, p.approval_status, p.confidence, "
                "p.updated_at, p.source_email_id, s.company_name AS supplier_name, s.email AS supplier_email, "
                "s.approval_status AS supplier_approval_status FROM supplier_parts p JOIN suppliers s ON s.id = p.supplier_id "
                "WHERE p.part_number = :part_number AND (p.quantity_available IS NULL OR p.quantity_available >= :quantity) "
                "AND (p.approval_status = 'Approved' OR s.approval_status = 'Approved') "
                "ORDER BY p.updated_at DESC, p.unit_cost ASC LIMIT 50"
            ), {"part_number": part_number.strip().upper(), "quantity": max(1, int(quantity_needed))}).mappings().all()
            return [dict(row) for row in rows]

    def search_supplier_offers(self, query: str, condition: str | None = None) -> list[dict[str, Any]]:
        normalized = str(query or "").strip().upper()
        if not normalized:
            return []
        condition_sql = "AND UPPER(COALESCE(p.condition_code, '')) = :condition" if condition else ""
        with self._read() as connection:
            rows = connection.execute(text(
                "SELECT p.id AS supplier_part_id, p.supplier_id, p.part_number, p.quantity_available, p.unit_cost, "
                "p.certificate_type, p.lead_time_days, p.condition_code, p.approval_status, p.confidence, "
                "p.updated_at, p.source_email_id, s.company_name AS supplier_name, s.email AS supplier_email "
                "FROM supplier_parts p JOIN suppliers s ON s.id = p.supplier_id "
                "WHERE p.part_number LIKE :query " + condition_sql + " "
                "AND (p.approval_status = 'Approved' OR s.approval_status = 'Approved') "
                "ORDER BY p.updated_at DESC, p.unit_cost ASC LIMIT 50"
            ), {"query": f"%{normalized}%", "condition": str(condition or "").upper()}).mappings().all()
            return [dict(row) for row in rows]

    def schedule_communication_task(self, *, task_key: str, task_type: str, mailbox: str, recipient: str, subject: str, body: str, due_at: datetime, reply_to: str | None = None) -> dict[str, Any]:
        task_id = f"COM-{uuid.uuid5(uuid.NAMESPACE_URL, task_key).hex[:16].upper()}"
        with self._begin() as connection:
            row = connection.execute(text(
                "INSERT INTO communication_tasks (id, task_key, recipient, subject, body, task_type, mailbox, reply_to, status, attempts, max_attempts, due_at, created_at) "
                "VALUES (:id, :key, :recipient, :subject, :body, :type, :mailbox, :reply_to, 'pending', 0, 5, :due, now()) "
                "ON CONFLICT (task_key) DO UPDATE SET task_key = EXCLUDED.task_key RETURNING *"
            ), {"id": task_id, "key": task_key, "recipient": recipient, "subject": subject, "body": body,
                "type": task_type, "mailbox": mailbox, "reply_to": reply_to, "due": due_at}).mappings().one()
            return dict(row)

    def list_due_communication_tasks(self, now: datetime | None = None) -> list[dict[str, Any]]:
        with self._read() as connection:
            rows = connection.execute(text(
                "SELECT * FROM communication_tasks WHERE status = 'pending' AND due_at <= COALESCE(:now, now()) ORDER BY due_at LIMIT 100"
            ), {"now": now}).mappings().all()
            return [dict(row) for row in rows]

    def update_communication_task(self, task_id: str, *, status: str, error: str | None = None) -> None:
        with self._begin() as connection:
            connection.execute(text(
                "UPDATE communication_tasks SET status = :status, attempts = attempts + 1, sent_at = CASE WHEN :status = 'sent' THEN now() ELSE sent_at END, last_error = :error WHERE id = :id"
            ), {"status": status, "error": error, "id": task_id})

    def cancel_communication_task(self, task_key: str) -> None:
        with self._begin() as connection:
            connection.execute(text("UPDATE communication_tasks SET status = 'cancelled' WHERE task_key = :key AND status = 'pending'"), {"key": task_key})

    def retry_communication_task(self, task_id: str, error: str) -> None:
        with self._begin() as connection:
            connection.execute(text(
                "UPDATE communication_tasks SET attempts = attempts + 1, status = CASE WHEN attempts + 1 >= max_attempts THEN 'dead_letter' ELSE 'pending' END, "
                "last_error = :error, due_at = now() + LEAST(interval '1 hour', interval '5 seconds' * power(2, GREATEST(attempts, 0))) WHERE id = :id"
            ), {"error": str(error)[:1000], "id": task_id})
