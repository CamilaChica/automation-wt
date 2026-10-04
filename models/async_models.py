"""SQLAlchemy 2 async persistence models for production migration."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AviationPart(Base):
    __tablename__ = "aviation_parts"
    __table_args__ = (Index("ix_aviation_parts_part_number", "part_number", unique=True),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    part_number: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    condition_code: Mapped[str | None] = mapped_column(String(8))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    warranty_terms: Mapped[str | None] = mapped_column(Text)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    supplier_quotes: Mapped[list["SupplierQuote"]] = relationship(back_populates="part", cascade="all, delete-orphan")


class SupplierQuote(Base):
    __tablename__ = "supplier_quotes"
    __table_args__ = (
        Index("ix_supplier_quotes_supplier_email", "supplier_email"),
        Index("ix_supplier_quotes_part_id_created_at", "part_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_email: Mapped[str] = mapped_column(String(320))
    part_id: Mapped[str] = mapped_column(ForeignKey("aviation_parts.id", ondelete="CASCADE"))
    quoted_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    raw_email_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    has_trace_docs: Mapped[bool] = mapped_column(Boolean, default=False)
    attachment_url: Mapped[str | None] = mapped_column(Text)
    quantity_available: Mapped[int | None] = mapped_column(Integer)
    condition_code: Mapped[str | None] = mapped_column(String(8))
    certificate_type: Mapped[str | None] = mapped_column(String(64))
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    availability_location: Mapped[str | None] = mapped_column(Text)
    warranty_terms: Mapped[str | None] = mapped_column(Text)
    trace_documents: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    part: Mapped[AviationPart] = relationship(back_populates="supplier_quotes")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        Index(
            "uq_purchase_orders_received_message",
            "received_message_id",
            unique=True,
            postgresql_where=text("received_message_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    po_number: Mapped[str] = mapped_column(String(64), unique=True)
    customer_email: Mapped[str] = mapped_column(String(320))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(32), default="Pending_PO_Review")
    po_document_url: Mapped[str | None] = mapped_column(Text)
    quote_id: Mapped[str | None] = mapped_column(String(64))
    rfq_id: Mapped[str | None] = mapped_column(String(64))
    received_message_id: Mapped[str | None] = mapped_column(String(512))
    attachment_metadata: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PromptTechniqueRecord(Base):
    __tablename__ = "prompt_techniques"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(Text)
    template: Mapped[str] = mapped_column(Text)
    examples: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PromptSecurityRecord(Base):
    __tablename__ = "prompt_security_policies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    sanitize_input: Mapped[bool] = mapped_column(Boolean, default=True)
    detect_injection: Mapped[bool] = mapped_column(Boolean, default=True)
    mask_pii: Mapped[bool] = mapped_column(Boolean, default=True)
    prevent_jailbreaks: Mapped[bool] = mapped_column(Boolean, default=True)
    block_injection: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScalingPromptRecord(Base):
    __tablename__ = "scaling_prompts"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_scaling_prompts_name_version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(Integer)
    template: Mapped[str] = mapped_column(Text)
    variables: Mapped[list[str]] = mapped_column(JSONB, default=list)
    prompt_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BusinessPolicyRecord(Base):
    __tablename__ = "business_policies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    policy_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(Text)
    policy_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class RagVectorRecord(Base):
    __tablename__ = "rag_vector_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(256), index=True)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(JSONB)
    embedding_provider: Mapped[str] = mapped_column(String(32))
    embedding_model: Mapped[str] = mapped_column(String(128))
    record_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())