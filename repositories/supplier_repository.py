from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.operational_models import SupplierPartRecord, SupplierRecord


class SupplierRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, supplier_id: str) -> SupplierRecord | None:
        return await self.session.get(SupplierRecord, supplier_id)

    async def by_email(self, email: str) -> SupplierRecord | None:
        result = await self.session.scalars(
            select(SupplierRecord).where(func.lower(SupplierRecord.email) == email.strip().lower())
        )
        return result.first()

    async def parts_for_supplier(self, supplier_id: str) -> list[SupplierPartRecord]:
        result = await self.session.scalars(
            select(SupplierPartRecord).where(SupplierPartRecord.supplier_id == supplier_id)
        )
        return list(result)

    async def create(self, **values) -> SupplierRecord:
        record = SupplierRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def create_part(self, **values) -> SupplierPartRecord:
        record = SupplierPartRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record