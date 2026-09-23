"""Shared PostgreSQL operational persistence models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, JSON, String, Text, UniqueConstraint, func
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
