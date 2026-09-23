from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.operational_models import QuoteItemRecord, QuoteRecord


class QuoteRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, quote_id: str) -> QuoteRecord | None:
        return await self.session.get(QuoteRecord, quote_id)

    async def for_rfq(self, rfq_id: str) -> list[QuoteRecord]:
        result = await self.session.scalars(select(QuoteRecord).where(QuoteRecord.rfq_id == rfq_id))
        return list(result)

    async def create(self, **values) -> QuoteRecord:
        record = QuoteRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def add_item(self, **values) -> QuoteItemRecord:
        record = QuoteItemRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record
