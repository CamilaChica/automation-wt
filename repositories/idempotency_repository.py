from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from models.operational_models import InboundMessageIdempotencyRecord


class IdempotencyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def claim(self, message_id: str, mailbox: str) -> bool:
        """Claim a message within the caller's transaction."""
        existing = await self.session.get(InboundMessageIdempotencyRecord, message_id, with_for_update=True)
        if existing is not None:
            return False
        self.session.add(InboundMessageIdempotencyRecord(
            message_id=message_id,
            mailbox=mailbox,
            processed_at=datetime.now(timezone.utc),
            status="processing",
        ))
        await self.session.flush()
        return True

    async def mark_processed(self, message_id: str) -> None:
        record = await self.session.get(InboundMessageIdempotencyRecord, message_id)
        if record is not None:
            record.status = "processed"
            await self.session.flush()
