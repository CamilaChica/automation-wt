from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.operational_models import RFQItemRecord, RFQRecord, SupplierOfferRecord


class RFQRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, rfq_id: str) -> RFQRecord | None:
        return await self.session.get(RFQRecord, rfq_id)

    async def create(self, **values) -> RFQRecord:
        record = RFQRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def add_item(self, **values) -> RFQItemRecord:
        record = RFQItemRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def offers(self, part_number: str) -> list[SupplierOfferRecord]:
        result = await self.session.scalars(
            select(SupplierOfferRecord).where(SupplierOfferRecord.part_number == part_number.upper())
        )
        return list(result)
