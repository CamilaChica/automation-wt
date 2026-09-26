"""Shared PostgreSQL operational persistence models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from models.async_models import Base


class RFQRecord(Base):
    __tablename__ = "rfqs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_email: Mapped[str] = mapped_column(String(320), index=True)
    customer_name: Mapped[str] = mapped_column(String(255), default="")
    raw_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64), index=True, default="Intake")
    thread_id: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RFQItemRecord(Base):
    __tablename__ = "rfq_items"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    rfq_id: Mapped[str] = mapped_column(String(64), index=True)
    part_number: Mapped[str] = mapped_column(String(80), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    condition_code: Mapped[str | None] = mapped_column(String(8))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class SupplierOfferRecord(Base):
    __tablename__ = "supplier_offers"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    rfq_id: Mapped[str | None] = mapped_column(String(64), index=True)
    supplier_email: Mapped[str] = mapped_column(String(320), index=True)
    part_number: Mapped[str] = mapped_column(String(80), index=True)
    quantity_available: Mapped[int | None] = mapped_column(Integer)
    unit_cost: Mapped[float | None] = mapped_column()
    condition_code: Mapped[str | None] = mapped_column(String(8))
    certificate_type: Mapped[str | None] = mapped_column(String(64))
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    source_message_id: Mapped[str | None] = mapped_column(String(512), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuoteRecord(Base):
    __tablename__ = "quotes"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    rfq_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True, default="Draft")
    total_amount: Mapped[float] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuoteItemRecord(Base):
    __tablename__ = "quote_items"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    quote_id: Mapped[str] = mapped_column(String(64), index=True)
    part_number: Mapped[str] = mapped_column(String(80))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[float] = mapped_column()
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class CommunicationRecord(Base):
    __tablename__ = "communications"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    recipient: Mapped[str] = mapped_column(String(320))
    sender: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEventRecord(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkflowStateRecord(Base):
    __tablename__ = "workflow_state"
    entity_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CommunicationTaskRecord(Base):
    __tablename__ = "communication_tasks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    recipient: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True, default="pending")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InboundMessageIdempotencyRecord(Base):
    __tablename__ = "inbound_message_idempotency"
    message_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    mailbox: Mapped[str] = mapped_column(String(128), index=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(32), default="processed")


class AgentHandoffRecord(Base):
    __tablename__ = "agent_handoffs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    from_agent: Mapped[str] = mapped_column(String(128))
    to_agent: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OperatorReviewRecord(Base):
    __tablename__ = "operator_review_queue"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    task: Mapped[str] = mapped_column(String(128), index=True)
    prompt_version: Mapped[str | None] = mapped_column(String(128))
    entity_id: Mapped[str | None] = mapped_column(String(128), index=True)
    source_text: Mapped[str] = mapped_column(Text)
    extraction_json: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    hold_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(32), index=True, default="PENDING")
    decision: Mapped[str | None] = mapped_column(String(16))
    decision_by: Mapped[str | None] = mapped_column(String(320))
    decision_payload: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LLMTelemetryRecord(Base):
    __tablename__ = "llm_telemetry"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task: Mapped[str] = mapped_column(String(128), index=True)
    prompt_version: Mapped[str] = mapped_column(String(128))
    model_id: Mapped[str] = mapped_column(String(128))
    model_calls_json: Mapped[str] = mapped_column(Text, default="[]")
    latency_ms: Mapped[float] = mapped_column(Float)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    validation_result: Mapped[str] = mapped_column(String(64))
    operator_review_outcome: Mapped[str | None] = mapped_column(String(32))
    review_queue_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AutomationEventRecord(Base):
    __tablename__ = "automation_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    execution_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CarrierWebhookEventRecord(Base):
    __tablename__ = "carrier_webhook_events"
    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OperationsStateRecord(Base):
    __tablename__ = "operations_state"
    state_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
