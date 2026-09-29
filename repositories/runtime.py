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
    )


async def _probe(session: AsyncSession, models: tuple[type, ...]) -> bool:
    try:
        async with session.begin_nested():
            for model in models:
                await session.execute(select(model).limit(0))
        return True
    except Exception:
        return False