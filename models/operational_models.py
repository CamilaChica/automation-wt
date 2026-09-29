"""Shared PostgreSQL operational persistence models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CHAR, DateTime, Float, ForeignKey, Index, Integer, JSON, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.async_models import Base


class RFQRecord(Base):
    __tablename__ = "rfqs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_email: Mapped[str] = mapped_column(String(320), index=True)
    customer_id: Mapped[str | None] = mapped_column(String(64), index=True)
    customer_name: Mapped[str] = mapped_column(String(255), default="")
    part_number: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)
    condition_requested: Mapped[str | None] = mapped_column(String(32))
    certification_requested: Mapped[str | None] = mapped_column(String(255))
    destination: Mapped[str | None] = mapped_column(String(512))
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
    description: Mapped[str | None] = mapped_column(Text)
    target_price: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(3))
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
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    recipient: Mapped[str] = mapped_column(String(320))
    sender: Mapped[str] = mapped_column(String(320))
    channel: Mapped[str | None] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(255), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    message_type: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_received: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEventRecord(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_entity_id", "entity_id"),
        Index("ix_audit_events_entity_created", "entity_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(64))
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
    __table_args__ = (UniqueConstraint("task_key", name="communication_tasks_task_key_key"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_key: Mapped[str] = mapped_column(String(255))
    recipient: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    task_type: Mapped[str] = mapped_column(String(64), default="email")
    mailbox: Mapped[str] = mapped_column(String(128), default="sales")
    reply_to: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), index=True, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    last_error: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InboundMessageIdempotencyRecord(Base):
    __tablename__ = "inbound_message_idempotency"
    message_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    mailbox: Mapped[str] = mapped_column(String(128), index=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(32), default="processed")


class InboundEmailRecord(Base):
    __tablename__ = "inbound_emails"
    __table_args__ = (
        UniqueConstraint("message_id", name="inbound_emails_message_id_key"),
        Index("ix_inbound_emails_message_id", "message_id"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mailbox: Mapped[str] = mapped_column(String(128), index=True)
    message_id: Mapped[str] = mapped_column(String(512))
    sender: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processing_status: Mapped[str] = mapped_column(String(32), default="received")
    extraction_error: Mapped[str | None] = mapped_column(Text)


class RawEmailRecord(Base):
    __tablename__ = "raw_emails"
    __table_args__ = (
        UniqueConstraint("mailbox", "provider_message_id", name="uq_raw_emails_mailbox_provider_message"),
        Index("ix_raw_emails_mailbox_received", "mailbox", "received_at"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mailbox: Mapped[str] = mapped_column(String(128))
    provider_message_id: Mapped[str] = mapped_column(String(512))
    internet_message_id: Mapped[str | None] = mapped_column(String(998), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(512))
    sender: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    body: Mapped[str] = mapped_column(Text, default="")
    raw_mime: Mapped[bytes | None] = mapped_column(LargeBinary)
    headers: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    attachments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    processing_status: Mapped[str] = mapped_column(String(32), default="received")
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupplierInventoryImportRecord(Base):
    __tablename__ = "supplier_inventory_imports"
    __table_args__ = (
        UniqueConstraint("source_message_id", "content_sha256", name="uq_supplier_inventory_imports_source"),
        Index("ix_supplier_inventory_imports_created", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mailbox: Mapped[str] = mapped_column(String(128))
    source_message_id: Mapped[str] = mapped_column(String(512))
    sender: Mapped[str | None] = mapped_column(String(320))
    filename: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(CHAR(64))
    parser: Mapped[str] = mapped_column(String(32))
    sheet_name: Mapped[str | None] = mapped_column(Text)
    header_map: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    rejected_rows: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupplierInventoryRowRecord(Base):
    __tablename__ = "supplier_inventory_rows"
    __table_args__ = (UniqueConstraint("import_id", "row_number", name="uq_supplier_inventory_rows_import_row"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    import_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("supplier_inventory_imports.id", ondelete="CASCADE")
    )
    row_number: Mapped[int] = mapped_column(Integer)
    part_number: Mapped[str | None] = mapped_column(String(128), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    quantity_available: Mapped[int | None] = mapped_column(Integer)
    condition_code: Mapped[str | None] = mapped_column(String(32))
    unit_price: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(3))
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    certificate_type: Mapped[str | None] = mapped_column(Text)
    availability_location: Mapped[str | None] = mapped_column(Text)
    raw_values: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="operator_review_queue_idempotency_key_key"),
        Index("ix_operator_review_queue_status_created", "status", "created_at"),
        Index("ix_operator_review_queue_entity", "entity_id"),
        Index("ix_operator_review_queue_task", "task"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    task: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(128))
    entity_id: Mapped[str | None] = mapped_column(String(128))
    source_text: Mapped[str] = mapped_column(Text)
    extraction_json: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    hold_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    decision: Mapped[str | None] = mapped_column(String(16))
    decision_by: Mapped[str | None] = mapped_column(String(320))
    decision_payload: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AuditLogRecord(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_rfq_created", "rfq_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rfq_id: Mapped[str] = mapped_column(String(64))
    agent_name: Mapped[str] = mapped_column(String(128))
    action_type: Mapped[str] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="SUCCESS")
    payload_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmployeeProfileRecord(Base):
    __tablename__ = "employee_profiles"

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    job_title: Mapped[str] = mapped_column(String(120))
    is_online: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmployeeTimeEventRecord(Base):
    __tablename__ = "employee_time_events"
    __table_args__ = (
        Index("ix_employee_time_events_user_time", "user_id", "occurred_at", "id"),
        Index("ix_employee_time_events_email_time", "email", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class NegotiationSessionRecord(Base):
    __tablename__ = "negotiation_sessions"
    __table_args__ = (
        UniqueConstraint("supplier_email", "part_number", name="uq_negotiation_sessions_supplier_part"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_email: Mapped[str] = mapped_column(String(320))
    part_number: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LLMTelemetryRecord(Base):
    __tablename__ = "llm_telemetry"
    __table_args__ = (
        Index("ix_llm_telemetry_task_created", "task", "created_at"),
        Index("ix_llm_telemetry_review_queue", "review_queue_id"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(128))
    model_id: Mapped[str] = mapped_column(String(128))
    model_calls_json: Mapped[str] = mapped_column(Text, default="[]")
    latency_ms: Mapped[float] = mapped_column(Float)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    validation_result: Mapped[str] = mapped_column(String(64))
    operator_review_outcome: Mapped[str | None] = mapped_column(String(32))
    review_queue_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AutomationEventRecord(Base):
    __tablename__ = "automation_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="automation_events_idempotency_key_key"),
        Index("ix_automation_events_status_created", "status", "created_at"),
        Index("ix_automation_events_entity", "entity_type", "entity_id"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(128))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(64))
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


class CustomerRecord(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255))
    contact_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CustomerQuoteRecord(Base):
    __tablename__ = "customer_quotes"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    rfq_id: Mapped[str] = mapped_column(String(64), index=True)
    quote_number: Mapped[str] = mapped_column(String(64), unique=True)
    unit_price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer)
    total_price: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    lead_time: Mapped[int | None] = mapped_column(Integer)
    condition: Mapped[str | None] = mapped_column(String(32))
    certification: Mapped[str | None] = mapped_column(String(255))
    valid_until: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CustomerQuoteItemRecord(Base):
    __tablename__ = "customer_quote_items"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    quote_id: Mapped[str] = mapped_column(String(64), index=True)
    rfq_item_id: Mapped[str | None] = mapped_column(String(64))
    part_number: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[int] = mapped_column(Integer)
    condition: Mapped[str | None] = mapped_column(String(32))
    certification: Mapped[str] = mapped_column(String(255))
    unit_price: Mapped[float] = mapped_column(Float)
    lead_time: Mapped[int | None] = mapped_column(Integer)
    attachments: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OperationalRecord(Base):
    __tablename__ = "operational_records"
    __table_args__ = (Index("ix_operational_records_domain_updated", "domain", "updated_at"),)
    domain: Mapped[str] = mapped_column(String(64), primary_key=True)
    record_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SupplierRecord(Base):
    __tablename__ = "suppliers"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255), index=True)
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    phone: Mapped[str | None] = mapped_column(String(64))
    approval_status: Mapped[str] = mapped_column(String(32), default="Pending")
    itar_certified: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str] = mapped_column(String(32), default="email")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class QuarantineQuoteItemRecord(Base):
    __tablename__ = "quarantine_quote_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    quote_id: Mapped[str | None] = mapped_column(String(64))
    rfq_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuarantineSupplierProfileRecord(Base):
    __tablename__ = "quarantine_supplier_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    matched_supplier_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupplierPartRecord(Base):
    __tablename__ = "supplier_parts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"), index=True)
    part_number: Mapped[str] = mapped_column(String(80), index=True)
    condition_code: Mapped[str | None] = mapped_column(String(8))
    description: Mapped[str | None] = mapped_column(Text)
    quantity_available: Mapped[int | None] = mapped_column(Integer)
    unit_cost: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    certificate_type: Mapped[str | None] = mapped_column(String(128))
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    availability_location: Mapped[str | None] = mapped_column(String(255))
    warranty_terms: Mapped[str | None] = mapped_column(Text)
    trace_documents: Mapped[str | None] = mapped_column(Text)
    source_email_id: Mapped[str | None] = mapped_column(String(512), unique=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    approval_status: Mapped[str] = mapped_column(String(32), default="Pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OutboxMessageRecord(Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        UniqueConstraint("deduplication_key", name="outbox_messages_deduplication_key_key"),
        Index("ix_outbox_messages_status", "status", "available_at"),
        Index("ix_outbox_messages_task", "communication_task_id"),
        Index("ix_outbox_messages_entity", "entity_id"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    deduplication_key: Mapped[str] = mapped_column(String(255))
    entity_id: Mapped[str | None] = mapped_column(String(128))
    mailbox: Mapped[str] = mapped_column(String(128))
    recipient: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(512))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    reply_to: Mapped[str | None] = mapped_column(String(512))
    communication_task_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=5)
    error_message: Mapped[str | None] = mapped_column(Text)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sending_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
