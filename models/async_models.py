"""SQLAlchemy 2 async persistence models for production migration."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AviationPart(Base):
    __tablename__ = "aviation_parts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    part_number: Mapped[str] = mapped_column(String(80), unique=True, index=True)
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

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_email: Mapped[str] = mapped_column(String(320), index=True)
    part_id: Mapped[str] = mapped_column(ForeignKey("aviation_parts.id", ondelete="CASCADE"), index=True)
    quoted_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    raw_email_id: Mapped[str | None] = mapped_column(String(128), index=True)
    has_trace_docs: Mapped[bool] = mapped_column(Boolean, default=False)
    attachment_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    part: Mapped[AviationPart] = relationship(back_populates="supplier_quotes")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    po_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    customer_email: Mapped[str] = mapped_column(String(320))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(32), default="Pending_PO_Review", index=True)
    po_document_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())