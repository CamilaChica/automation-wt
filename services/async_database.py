"""Async SQLAlchemy session and idempotent production repositories."""

from __future__ import annotations

import os
import asyncio
import socket
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import AsyncIterator
from urllib.parse import urlsplit

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from models.async_models import AviationPart, Base, SupplierQuote


def _database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    fallback = os.getenv("DATABASE_URL_FALLBACK", "").strip()
    if value and fallback:
        parsed_host = urlsplit(value.replace("postgresql+asyncpg://", "postgresql://", 1)).hostname
        try:
            if parsed_host:
                socket.getaddrinfo(parsed_host, None)
        except socket.gaierror:
            value = fallback
    if value.startswith("postgresql://"):
        value = value.replace("postgresql://", "postgresql+asyncpg://", 1)
    return value


def create_engine_from_environment() -> AsyncEngine:
    url = _database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is required for the async PostgreSQL persistence layer.")
    return create_async_engine(url, pool_pre_ping=True, pool_recycle=1800)


async def preflight_database(engine: AsyncEngine | None = None) -> None:
    """Verify DNS and database readiness before accepting work, with bounded backoff."""
    owns_engine = engine is None
    engine = engine or create_engine_from_environment()
    attempts = max(1, int(os.getenv("DATABASE_PREFLIGHT_ATTEMPTS", "5")))
    delay = max(0.1, float(os.getenv("DATABASE_PREFLIGHT_INITIAL_DELAY_SECONDS", "0.5")))
    maximum = max(delay, float(os.getenv("DATABASE_PREFLIGHT_MAX_DELAY_SECONDS", "8")))
    last_error: Exception | None = None
    try:
        for attempt in range(attempts):
            try:
                async with engine.connect() as connection:
                    await connection.exec_driver_sql("SELECT 1")
                return
            except Exception as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, maximum)
        raise RuntimeError(
            f"PostgreSQL preflight failed after {attempts} attempts ({type(last_error).__name__}). "
            "Check DATABASE_URL DNS/network access or configure DATABASE_URL_FALLBACK explicitly."
        ) from last_error
    finally:
        if owns_engine:
            await engine.dispose()


@asynccontextmanager
async def session_scope(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def upsert_aviation_part(session: AsyncSession, *, part_number: str, description: str = "", condition_code: str | None = None, unit_price: Decimal | None = None, currency: str = "USD", warranty_terms: str | None = None, lead_time_days: int | None = None) -> AviationPart:
    part_id = f"PART-{uuid.uuid4().hex[:12].upper()}"
    statement = insert(AviationPart).values(
        id=part_id,
        part_number=part_number.upper(),
        description=description,
        condition_code=condition_code,
        unit_price=unit_price,
        currency=currency,
        warranty_terms=warranty_terms,
        lead_time_days=lead_time_days,
    ).on_conflict_do_update(
        index_elements=[AviationPart.part_number],
        set_={
            "description": description,
            "condition_code": condition_code,
            "unit_price": unit_price,
            "currency": currency,
            "warranty_terms": warranty_terms,
            "lead_time_days": lead_time_days,
        },
    ).returning(AviationPart)
    result = await session.execute(statement)
    return result.scalar_one()


async def upsert_supplier_quote(session: AsyncSession, *, supplier_email: str, part_id: str, quoted_price: Decimal | None, raw_email_id: str | None, has_trace_docs: bool, attachment_url: str | None = None, quantity_available: int | None = None, condition_code: str | None = None, certificate_type: str | None = None, lead_time_days: int | None = None, availability_location: str | None = None, warranty_terms: str | None = None, trace_documents: str | None = None) -> SupplierQuote:
    quote_id = f"SQUOTE-{uuid.uuid4().hex[:12].upper()}"
    statement = insert(SupplierQuote).values(
        id=quote_id,
        supplier_email=supplier_email.lower(),
        part_id=part_id,
        quoted_price=quoted_price,
        raw_email_id=raw_email_id,
        has_trace_docs=has_trace_docs,
        attachment_url=attachment_url,
        quantity_available=quantity_available,
        condition_code=condition_code,
        certificate_type=certificate_type,
        lead_time_days=lead_time_days,
        availability_location=availability_location,
        warranty_terms=warranty_terms,
        trace_documents=trace_documents,
    ).on_conflict_do_nothing(index_elements=[SupplierQuote.raw_email_id]).returning(SupplierQuote)
    result = await session.execute(statement)
    quote = result.scalar_one_or_none()
    if quote:
        return quote
    existing = await session.scalar(select(SupplierQuote).where(SupplierQuote.raw_email_id == raw_email_id))
    if not existing:
        raise RuntimeError("Supplier quote upsert did not return or locate a quote row.")
    return existing


async def search_supplier_inventory(session: AsyncSession, *, query: str, condition_code: str | None = None) -> list[dict]:
    normalized = query.strip()
    if not normalized:
        return []
    statement = select(AviationPart, SupplierQuote).join(SupplierQuote, SupplierQuote.part_id == AviationPart.id).where(
        or_(AviationPart.part_number.ilike(f"%{normalized}%"), AviationPart.description.ilike(f"%{normalized}%"))
    )
    if condition_code:
        statement = statement.where(SupplierQuote.condition_code.ilike(condition_code.strip()))
    statement = statement.order_by(SupplierQuote.created_at.desc()).limit(50)
    rows = (await session.execute(statement)).all()
    return [{
        "part_number": part.part_number,
        "condition_code": quote.condition_code or part.condition_code or "NE",
        "quantity_available": quote.quantity_available or 0,
        "certificate_type": quote.certificate_type or "Available upon supplier confirmation",
        "has_full_trace": bool(quote.has_trace_docs),
        "lead_time_days": quote.lead_time_days,
        "availability_location": quote.availability_location,
    } for part, quote in rows]