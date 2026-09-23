from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from models.operational_models import WorkflowStateRecord


class WorkflowRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, entity_id: str) -> WorkflowStateRecord | None:
        return await self.session.get(WorkflowStateRecord, entity_id)

    async def set_state(self, entity_id: str, state: str, version: int = 1) -> WorkflowStateRecord:
        record = await self.get(entity_id)
        if record is None:
            record = WorkflowStateRecord(entity_id=entity_id, state=state, version=version)
            self.session.add(record)
        else:
            record.state = state
            record.version = version
        await self.session.flush()
        return record
