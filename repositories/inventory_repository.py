from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.operational_models import SupplierInventoryImportRecord, SupplierInventoryRowRecord


class InventoryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def import_for_source(
        self, source_message_id: str, content_sha256: str
    ) -> SupplierInventoryImportRecord | None:
        result = await self.session.scalars(
            select(SupplierInventoryImportRecord).where(
                SupplierInventoryImportRecord.source_message_id == source_message_id,
                SupplierInventoryImportRecord.content_sha256 == content_sha256,
            )
        )
        return result.first()

    async def create_import(self, **values) -> SupplierInventoryImportRecord:
        record = SupplierInventoryImportRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def add_rows(self, rows: list[dict]) -> list[SupplierInventoryRowRecord]:
        records = [SupplierInventoryRowRecord(**row) for row in rows]
        self.session.add_all(records)
        await self.session.flush()
        return records

    async def rows_for_import(self, import_id: str) -> list[SupplierInventoryRowRecord]:
        result = await self.session.scalars(
            select(SupplierInventoryRowRecord)
            .where(SupplierInventoryRowRecord.import_id == import_id)
            .order_by(SupplierInventoryRowRecord.row_number)
        )
        return list(result)