from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.operational_models import CustomerRecord, OperationalRecord, RFQItemRecord, RFQRecord, SupplierOfferRecord


class RFQRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, rfq_id: str) -> RFQRecord | None:
        return await self.session.get(RFQRecord, rfq_id)

    async def list(self) -> list[RFQRecord]:
        result = await self.session.scalars(
            select(RFQRecord).order_by(RFQRecord.created_at.desc(), RFQRecord.id)
        )
        return list(result)

    async def get_operational_record(self, domain: str, record_id: str) -> dict | None:
        record = await self.session.get(
            OperationalRecord, {"domain": domain, "record_id": record_id}
        )
        return dict(record.payload) if record else None

    async def list_operational_records(self, domain: str) -> dict[str, dict]:
        result = await self.session.scalars(
            select(OperationalRecord).where(OperationalRecord.domain == domain)
        )
        return {record.record_id: dict(record.payload) for record in result}

    async def create(self, **values) -> RFQRecord:
        record = RFQRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def create_from_payload(self, payload: dict) -> RFQRecord:
        customer_email = str(payload["customer_email"]).strip().lower()
        customer_id = f"CUS-{customer_email}"
        if len(customer_id) > 64:
            customer_id = f"CUS-{uuid.uuid5(uuid.NAMESPACE_URL, customer_email).hex[:32].upper()}"
        if await self.session.get(CustomerRecord, customer_id) is None:
            self.session.add(CustomerRecord(
                id=customer_id,
                company_name=payload["customer_name"],
                contact_name=payload["customer_name"],
                email=customer_email,
            ))
        record = RFQRecord(
            id=payload["id"],
            customer_id=customer_id,
            customer_email=customer_email,
            customer_name=payload["customer_name"],
            raw_text=payload["raw_text"],
            status=payload["status"],
            thread_id=payload.get("thread_id"),
        )
        self.session.add(record)
        self.session.add(OperationalRecord(
            domain="rfqs",
            record_id=record.id,
            payload=payload,
        ))
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
