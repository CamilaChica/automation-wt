from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.operational_models import InboundMessageIdempotencyRecord


class IdempotencyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def claim(self, message_id: str, mailbox: str) -> bool:
        """Atomically claim a Graph message; concurrent workers cannot both win."""
        statement = (
            insert(InboundMessageIdempotencyRecord)
            .values(
                message_id=message_id,
                mailbox=mailbox,
                processed_at=datetime.now(timezone.utc),
                status="processing",
            )
            .on_conflict_do_nothing(index_elements=[InboundMessageIdempotencyRecord.message_id])
            .returning(InboundMessageIdempotencyRecord.message_id)
        )
        result = await self.session.execute(statement)
        claimed_id = result.scalar_one_or_none()
        await self.session.flush()
        return claimed_id is not None

    async def mark_processed(self, message_id: str) -> None:
        record = await self.session.get(InboundMessageIdempotencyRecord, message_id)
        if record is not None:
            record.status = "processed"
            await self.session.flush()
