from __future__ import annotations

import json
import uuid

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.operational_models import OperationalRecord, SupplierPartRecord, SupplierRecord


class SupplierRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, supplier_id: str) -> SupplierRecord | None:
        return await self.session.get(SupplierRecord, supplier_id)

    async def get_profile(self, supplier_id: str) -> dict | None:
        record = await self.session.get(
            OperationalRecord, {"domain": "suppliers", "record_id": supplier_id}
        )
        if record:
            return dict(record.payload)
        supplier = await self.get(supplier_id)
        if supplier is None:
            return None
        return {
            "id": supplier.id,
            "company_name": supplier.company_name,
            "contact_name": supplier.company_name,
            "phone": supplier.phone or "",
            "email": supplier.email or "",
            "address_line1": "",
            "city": "",
            "state_province": "",
            "postal_code": "",
            "country": "US",
            "approval_status": supplier.approval_status,
            "itar_certified": supplier.itar_certified,
        }

    async def by_email(self, email: str) -> SupplierRecord | None:
        result = await self.session.scalars(
            select(SupplierRecord).where(func.lower(SupplierRecord.email) == email.strip().lower())
        )
        return result.first()

    async def list_suppliers(self) -> list[dict]:
        result = await self.session.scalars(
            select(SupplierRecord).order_by(SupplierRecord.company_name, SupplierRecord.id)
        )
        return [
            {
                "id": record.id,
                "company_name": record.company_name,
                "email": record.email,
                "phone": record.phone,
                "approval_status": record.approval_status,
                "itar_certified": record.itar_certified,
            }
            for record in result
        ]

    async def offers_for_part(self, part_number: str, quantity_needed: int = 1) -> list[dict]:
        normalized_part = part_number.strip().upper()
        quantity = max(1, int(quantity_needed))
        statement = (
            select(
                SupplierPartRecord.id.label("supplier_part_id"),
                SupplierPartRecord.supplier_id,
                SupplierPartRecord.part_number,
                SupplierPartRecord.quantity_available,
                SupplierPartRecord.unit_cost,
                SupplierPartRecord.certificate_type,
                SupplierPartRecord.lead_time_days,
                SupplierPartRecord.condition_code,
                SupplierPartRecord.approval_status,
                SupplierPartRecord.confidence,
                SupplierPartRecord.updated_at,
                SupplierPartRecord.source_email_id,
                SupplierRecord.company_name.label("supplier_name"),
                SupplierRecord.email.label("supplier_email"),
                SupplierRecord.approval_status.label("supplier_approval_status"),
            )
            .join(SupplierRecord, SupplierRecord.id == SupplierPartRecord.supplier_id)
            .where(
                func.upper(SupplierPartRecord.part_number) == normalized_part,
                or_(SupplierPartRecord.quantity_available.is_(None), SupplierPartRecord.quantity_available >= quantity),
                or_(SupplierPartRecord.approval_status == "Approved", SupplierRecord.approval_status == "Approved"),
            )
            .order_by(SupplierPartRecord.updated_at.desc(), SupplierPartRecord.unit_cost.asc())
            .limit(50)
        )
        result = await self.session.execute(statement)
        return [dict(row) for row in result.mappings().all()]

    async def search_offers(self, query: str, condition: str | None = None) -> list[dict]:
        normalized_query = str(query or "").strip().upper()
        if not normalized_query:
            return []
        statement = (
            select(
                SupplierPartRecord.id.label("supplier_part_id"),
                SupplierPartRecord.supplier_id,
                SupplierPartRecord.part_number,
                SupplierPartRecord.quantity_available,
                SupplierPartRecord.certificate_type,
                SupplierPartRecord.condition_code,
                SupplierRecord.approval_status.label("supplier_approval_status"),
            )
            .join(SupplierRecord, SupplierRecord.id == SupplierPartRecord.supplier_id)
            .where(
                SupplierPartRecord.part_number.ilike(f"%{normalized_query}%"),
                or_(SupplierPartRecord.approval_status == "Approved", SupplierRecord.approval_status == "Approved"),
            )
        )
        if condition:
            statement = statement.where(
                func.upper(func.coalesce(SupplierPartRecord.condition_code, "")) == condition.strip().upper()
            )
        statement = statement.order_by(
            SupplierPartRecord.updated_at.desc(), SupplierPartRecord.unit_cost.asc()
        ).limit(50)
        result = await self.session.execute(statement)
        return [dict(row) for row in result.mappings().all()]

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

    async def save_inventory_offer(
        self,
        *,
        supplier_name: str,
        supplier_email: str | None,
        part_number: str,
        quantity_available: int | None,
        unit_cost: float | None,
        certificate_type: str | None,
        lead_time_days: int | None,
        condition_code: str | None,
        source_email_id: str,
        description: str = "",
        availability_location: str | None = None,
        warranty_terms: str | None = None,
        trace_documents: list[str] | None = None,
        currency: str = "USD",
        confidence: float = 1.0,
        approval_status: str = "Pending",
    ) -> dict:
        normalized_email = supplier_email.strip().lower() if supplier_email else None
        existing_query = select(SupplierRecord).where(
            or_(
                SupplierRecord.company_name == supplier_name,
                func.lower(SupplierRecord.email) == normalized_email if normalized_email else text("false"),
            )
        ).limit(1)
        supplier = await self.session.scalar(existing_query)
        if supplier is None:
            identity = normalized_email or supplier_name.strip().lower()
            supplier_id = f"SUP-{uuid.uuid5(uuid.NAMESPACE_URL, identity).hex[:16].upper()}"
            supplier = SupplierRecord(
                id=supplier_id,
                company_name=supplier_name,
                email=normalized_email,
                approval_status=approval_status,
                source="email",
            )
            self.session.add(supplier)
            await self.session.flush()

        normalized_part = part_number.strip().upper()
        offer_id = f"SPO-{uuid.uuid5(uuid.NAMESPACE_URL, source_email_id).hex[:24].upper()}"
        values = {
            "id": offer_id,
            "supplier_id": supplier.id,
            "part_number": normalized_part,
            "condition_code": condition_code,
            "description": description,
            "quantity_available": quantity_available,
            "unit_cost": unit_cost,
            "currency": currency,
            "certificate_type": certificate_type,
            "lead_time_days": lead_time_days,
            "availability_location": availability_location,
            "warranty_terms": warranty_terms,
            "trace_documents": json.dumps(trace_documents or []),
            "source_email_id": source_email_id,
            "confidence": confidence,
            "approval_status": approval_status,
        }
        statement = postgres_insert(SupplierPartRecord).values(**values).on_conflict_do_update(
            index_elements=[SupplierPartRecord.source_email_id],
            set_={
                key: value for key, value in values.items()
                if key not in {"id", "source_email_id"}
            } | {"updated_at": func.now()},
        ).returning(SupplierPartRecord.id)
        saved_id = await self.session.scalar(statement)
        await self.session.flush()
        return {**values, "id": str(saved_id or offer_id), "supplier_name": supplier_name, "supplier_email": normalized_email}