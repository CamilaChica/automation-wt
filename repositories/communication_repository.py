from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.operational_models import CommunicationRecord


class CommunicationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **values) -> CommunicationRecord:
        record = CommunicationRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def for_entity(self, entity_id: str) -> list[CommunicationRecord]:
        result = await self.session.scalars(select(CommunicationRecord).where(CommunicationRecord.entity_id == entity_id))
        return list(result)
