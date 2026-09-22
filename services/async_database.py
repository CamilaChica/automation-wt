"""Async SQLAlchemy session and idempotent production repositories."""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from models.async_models import AviationPart, Base, SupplierQuote


def _database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if value.startswith("postgresql://"):
        value = value.replace("postgresql://", "postgresql+asyncpg://", 1)
    return value


def create_engine_from_environment() -> AsyncEngine:
    url = _database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is required for the async PostgreSQL persistence layer.")
    return create_async_engine(url, pool_pre_ping=True, pool_recycle=1800)


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


async def upsert_supplier_quote(session: AsyncSession, *, supplier_email: str, part_id: str, quoted_price: Decimal | None, raw_email_id: str | None, has_trace_docs: bool, attachment_url: str | None = None) -> SupplierQuote:
    quote_id = f"SQUOTE-{uuid.uuid4().hex[:12].upper()}"
    statement = insert(SupplierQuote).values(
        id=quote_id,
        supplier_email=supplier_email.lower(),
        part_id=part_id,
        quoted_price=quoted_price,
        raw_email_id=raw_email_id,
        has_trace_docs=has_trace_docs,
        attachment_url=attachment_url,
    ).on_conflict_do_nothing(index_elements=[SupplierQuote.raw_email_id]).returning(SupplierQuote)
    result = await session.execute(statement)
    quote = result.scalar_one_or_none()
    if quote:
        return quote
    existing = await session.scalar(select(SupplierQuote).where(SupplierQuote.raw_email_id == raw_email_id))
    if not existing:
        raise RuntimeError("Supplier quote upsert did not return or locate a quote row.")
    return existing