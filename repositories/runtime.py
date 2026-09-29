from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.operational_models import (
    QuoteItemRecord,
    QuoteRecord,
    RFQItemRecord,
    RFQRecord,
    SupplierInventoryImportRecord,
    SupplierInventoryRowRecord,
    SupplierOfferRecord,
    SupplierPartRecord,
    SupplierRecord,
    OperationalRecord,
)
from repositories.inventory_repository import InventoryRepository
from repositories.quote_repository import QuoteRepository
from repositories.rfq_repository import RFQRepository
from repositories.supplier_repository import SupplierRepository


@dataclass(frozen=True)
class OperationalRepositories:
    inventory: InventoryRepository
    rfq: RFQRepository
    supplier: SupplierRepository
    quote: QuoteRepository
    records: OperationalRecordRepository

    async def check_readiness(self) -> dict[str, bool]:
        return {
            "inventory": await _probe(self.inventory.session, (
                SupplierInventoryImportRecord, SupplierInventoryRowRecord, SupplierOfferRecord,
            )),
            "rfq": await _probe(self.rfq.session, (RFQRecord, RFQItemRecord)),
            "supplier": await _probe(self.supplier.session, (
                SupplierRecord, SupplierPartRecord, SupplierOfferRecord,
            )),
            "quote": await _probe(self.quote.session, (QuoteRecord, QuoteItemRecord)),
        }


def create_operational_repositories(session: AsyncSession) -> OperationalRepositories:
    """Bind all operational repositories to one request-scoped PostgreSQL session."""
    return OperationalRepositories(
        inventory=InventoryRepository(session),
        rfq=RFQRepository(session),
        supplier=SupplierRepository(session),
        quote=QuoteRepository(session),
        records=OperationalRecordRepository(session),
    )


class OperationalRecordRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, domain: str, record_id: str) -> dict | None:
        record = await self.session.get(
            OperationalRecord, {"domain": domain, "record_id": record_id}
        )
        return dict(record.payload) if record else None

    async def list(self, domain: str) -> dict[str, dict]:
        result = await self.session.scalars(
            select(OperationalRecord).where(OperationalRecord.domain == domain)
        )
        return {record.record_id: dict(record.payload) for record in result}

    async def list_by_payload_value(
        self, domain: str, field: str, value: str
    ) -> dict[str, dict]:
        result = await self.session.scalars(
            select(OperationalRecord).where(
                OperationalRecord.domain == domain,
                OperationalRecord.payload[field].as_string() == value,
            )
        )
        return {record.record_id: dict(record.payload) for record in result}


async def _probe(session: AsyncSession, models: tuple[type, ...]) -> bool:
    try:
        async with session.begin_nested():
            for model in models:
                await session.execute(select(model).limit(0))
        return True
    except Exception:
        return False