from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.async_models import PurchaseOrder
from models.db_models import RFQ
from models.operational_models import (
    AuditLogRecord,
    CustomerQuoteRecord,
    CustomerRecord,
    OperationalRecord,
    QuoteRecord,
    RFQItemRecord,
    RFQRecord,
    SupplierOfferRecord,
)
from services.workflow_states import canonical_state, validate_transition


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

    async def list_by_status(self, status: str) -> list[RFQRecord]:
        result = await self.session.scalars(
            select(RFQRecord)
            .where(RFQRecord.status == status)
            .order_by(RFQRecord.created_at.desc(), RFQRecord.id)
        )
        return list(result)

    async def audit_logs(self, rfq_id: str) -> list[AuditLogRecord]:
        result = await self.session.scalars(
            select(AuditLogRecord)
            .where(AuditLogRecord.rfq_id == rfq_id)
            .order_by(AuditLogRecord.created_at, AuditLogRecord.id)
        )
        return list(result)

    async def add_audit_log(
        self,
        *,
        rfq_id: str,
        agent_name: str,
        action_type: str,
        message: str,
        status: str = "SUCCESS",
        payload_json: str | None = None,
    ) -> AuditLogRecord:
        record = AuditLogRecord(
            rfq_id=rfq_id,
            agent_name=agent_name,
            action_type=action_type,
            message=message,
            status=status,
            payload_json=payload_json,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def approve_purchase_order(
        self, rfq_id: str, quote_id: str, operator_name: str, comments: str | None = None
    ) -> bool:
        result = await self.session.scalars(
            select(OperationalRecord)
            .where(OperationalRecord.domain == "rfqs", OperationalRecord.record_id == rfq_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        record = result.first()
        if record is None:
            return False
        rfq = RFQ.model_validate(record.payload)
        if rfq.status != "Pending_PO_Review":
            return False

        pending_orders = await self.session.scalars(
            select(PurchaseOrder)
            .where(
                PurchaseOrder.rfq_id == rfq_id,
                PurchaseOrder.quote_id == quote_id,
                PurchaseOrder.status == "Pending_PO_Review",
            )
            .with_for_update()
        )
        purchase_orders = list(pending_orders)
        if not purchase_orders:
            return False

        validate_transition(rfq.status, "Purchase_Order_Received")
        rfq.status = "Purchase_Order_Received"
        rfq.workflow_state = canonical_state(rfq.status)
        rfq.version += 1
        record.payload = rfq.model_dump(mode="json")
        relational_rfq = await self.session.get(RFQRecord, rfq_id)
        if relational_rfq is not None:
            relational_rfq.status = rfq.status
        for purchase_order in purchase_orders:
            purchase_order.status = rfq.status
        self.session.add(AuditLogRecord(
            rfq_id=rfq_id,
            agent_name="PurchaseOrderAgent",
            action_type="purchase_order_approved",
            message=f"PO approved by {operator_name}; downstream purchasing may proceed."
            + (f" Comments: {comments}" if comments else ""),
            status="SUCCESS",
        ))
        await self.session.flush()
        return True

    async def reject_quote(
        self, quote_id: str, rfq_id: str, operator_name: str, comments: str | None
    ) -> bool:
        quote_result = await self.session.scalars(
            select(OperationalRecord)
            .where(OperationalRecord.domain == "quotes", OperationalRecord.record_id == quote_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        quote_record = quote_result.first()
        rfq_result = await self.session.scalars(
            select(OperationalRecord)
            .where(OperationalRecord.domain == "rfqs", OperationalRecord.record_id == rfq_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        rfq_record = rfq_result.first()
        if quote_record is None or rfq_record is None:
            return False

        quote = dict(quote_record.payload)
        rfq = RFQ.model_validate(rfq_record.payload)
        if quote.get("rfq_id") != rfq_id or rfq.status == "Rejected":
            return False
        try:
            validate_transition(rfq.status, "Rejected")
        except ValueError:
            return False
        quote["status"] = "Rejected"
        quote["approved_by"] = operator_name
        quote["approved_at"] = datetime.now(timezone.utc).isoformat()
        if comments:
            quote["comments"] = comments
        quote["version"] = int(quote.get("version") or 1) + 1
        quote_record.payload = quote

        relational_quote = await self.session.get(QuoteRecord, quote_id)
        if relational_quote is not None:
            relational_quote.status = "Rejected"
        customer_quote = await self.session.get(CustomerQuoteRecord, quote_id)
        if customer_quote is not None:
            customer_quote.status = "Rejected"

        rfq.status = "Rejected"
        rfq.workflow_state = canonical_state(rfq.status)
        rfq.version += 1
        rfq_record.payload = rfq.model_dump(mode="json")
        relational_rfq = await self.session.get(RFQRecord, rfq_id)
        if relational_rfq is not None:
            relational_rfq.status = "Rejected"
        self.session.add(AuditLogRecord(
            rfq_id=rfq_id,
            agent_name="Orchestrator",
            action_type="human_rejection",
            message=f"Quote rejected by {operator_name}. Reason: {comments or ''}".rstrip(),
            status="WARNING",
        ))
        await self.session.flush()
        return True

    async def receive_purchase_order(
        self,
        *,
        po_id: str,
        po_number: str,
        received_message_id: str | None = None,
        quote_id: str,
        rfq_id: str,
        customer_email: str,
        total_amount: float,
        attachment_metadata: list[dict],
    ) -> bool:
        result = await self.session.scalars(
            select(OperationalRecord)
            .where(OperationalRecord.domain == "rfqs", OperationalRecord.record_id == rfq_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        record = result.first()
        if record is None:
            return False
        rfq = RFQ.model_validate(record.payload)
        if rfq.status in {"Purchase_Order_Received", "Pending_PO_Review"}:
            return False

        validate_transition(rfq.status, "Pending_PO_Review")
        inserted_id = await self.session.scalar(
            postgres_insert(PurchaseOrder)
            .values(
                id=po_id,
                po_number=po_number,
                received_message_id=received_message_id,
                customer_email=customer_email,
                total_amount=total_amount,
                status="Pending_PO_Review",
                quote_id=quote_id,
                rfq_id=rfq_id,
                attachment_metadata=attachment_metadata,
            )
            .on_conflict_do_nothing()
            .returning(PurchaseOrder.id)
        )
        if inserted_id is None:
            return False

        rfq.status = "Pending_PO_Review"
        rfq.workflow_state = canonical_state(rfq.status)
        rfq.version += 1
        record.payload = rfq.model_dump(mode="json")
        relational_rfq = await self.session.get(RFQRecord, rfq_id)
        if relational_rfq is not None:
            relational_rfq.status = rfq.status
        self.session.add(AuditLogRecord(
            rfq_id=rfq_id,
            agent_name="PurchaseOrderAgent",
            action_type="purchase_order_received",
            message=f"Purchase order {po_number} received; fulfillment and invoicing are blocked pending human review.",
            status="SUCCESS",
            payload_json=None,
        ))
        await self.session.flush()
        return True

    async def get_operational_record(self, domain: str, record_id: str) -> dict | None:
        record = await self.session.get(
            OperationalRecord, {"domain": domain, "record_id": record_id}
        )
        return dict(record.payload) if record else None

    async def record_pn_confirmation(self, rfq_id: str, confirmed: list[str], close_request: bool) -> None:
        record = await self.session.get(
            OperationalRecord, {"domain": "rfqs", "record_id": rfq_id}, with_for_update=True
        )
        if record is None:
            raise ValueError("RFQ not found for part-number confirmation.")
        rfq = RFQ.model_validate(record.payload)
        if rfq.automation_paused:
            raise ValueError("RFQ automation is paused; confirmation requires operator review.")
        state_record = await self.session.get(
            OperationalRecord, {"domain": "rfq_pipeline_state", "record_id": rfq_id},
            with_for_update=True,
        )
        if state_record is None:
            raise ValueError("Part-number confirmation state is missing.")
        state = dict(state_record.payload)
        if not set(confirmed).issubset(set(state.get("pn_confirmation_required") or [])):
            raise ValueError("Part-number confirmation is no longer pending.")
        state["pn_confirmation_required"] = [
            part for part in state.get("pn_confirmation_required", []) if part not in confirmed
        ]
        state["no_quote_parts"] = sorted(set(state.get("no_quote_parts", [])) | set(confirmed))
        state_record.payload = state
        if close_request:
            validate_transition(rfq.status, "No_Quote")
            rfq.status = "No_Quote"
            rfq.workflow_state = canonical_state("No_Quote")
            rfq.version += 1
            record.payload = rfq.model_dump(mode="json")
            relational = await self.session.get(RFQRecord, rfq_id)
            if relational is not None:
                relational.status = "No_Quote"
        else:
            rfq.automation_paused = True
            rfq.pause_reason = "Confirmed No Quote line in a mixed RFQ; remaining lines require operator review."
            record.payload = rfq.model_dump(mode="json")
        await self.add_audit_log(
            rfq_id=rfq_id, agent_name="CatalogInquiryProtocol", action_type="PN_CONFIRMED_NO_QUOTE",
            message=f"Customer confirmed part number(s): {', '.join(confirmed)}; no offer is available.",
        )

    async def reset_failed_intake(self, rfq_id: str, audit_message: str) -> bool:
        result = await self.session.scalars(
            select(OperationalRecord)
            .where(OperationalRecord.domain == "rfqs", OperationalRecord.record_id == rfq_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        record = result.first()
        if record is None:
            return False
        rfq = RFQ.model_validate(record.payload)
        if rfq.status != "Intake_Failed":
            raise ValueError("Only Intake_Failed RFQs can be reset.")
        validate_transition(rfq.status, "Intake")
        rfq.status = "Intake"
        rfq.workflow_state = canonical_state("Intake")
        rfq.version += 1
        record.payload = rfq.model_dump(mode="json")
        relational_rfq = await self.session.get(RFQRecord, rfq_id)
        if relational_rfq is not None:
            relational_rfq.status = "Intake"
        self.session.add(AuditLogRecord(
            rfq_id=rfq_id,
            agent_name="AutomationControl",
            action_type="intake_reset",
            message=audit_message,
            status="WARNING",
        ))
        await self.session.flush()
        return True

    async def set_automation_paused(
        self, rfq_id: str, paused: bool, reason: str | None, operator: str
    ) -> dict | None:
        result = await self.session.scalars(
            select(OperationalRecord)
            .where(OperationalRecord.domain == "rfqs", OperationalRecord.record_id == rfq_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        record = result.first()
        if record is None:
            return None
        payload = dict(record.payload)
        pause_reason = reason.strip() if paused and reason and reason.strip() else None
        payload["automation_paused"] = paused
        payload["pause_reason"] = pause_reason
        payload["version"] = int(payload.get("version") or 1) + 1
        record.payload = payload
        self.session.add(AuditLogRecord(
            rfq_id=rfq_id,
            agent_name="AutomationControl",
            action_type="automation_pause" if paused else "automation_resume",
            message=f"Automation {'paused' if paused else 'resumed'} by {operator}."
            + (f" Reason: {pause_reason}" if pause_reason else ""),
            status="WARNING" if paused else "SUCCESS",
        ))
        await self.session.flush()
        return {
            "rfq_id": rfq_id,
            "automation_paused": paused,
            "pause_reason": pause_reason,
        }

    async def record_trace_decision(
        self, rfq_id: str, decision: str, reason: str
    ) -> dict | None:
        result = await self.session.scalars(
            select(OperationalRecord)
            .where(OperationalRecord.domain == "rfqs", OperationalRecord.record_id == rfq_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        record = result.first()
        if record is None:
            return None
        payload = dict(record.payload)
        if decision == "freeze":
            payload["automation_paused"] = True
            payload["pause_reason"] = reason
            payload["version"] = int(payload.get("version") or 1) + 1
            record.payload = payload
        self.session.add(AuditLogRecord(
            rfq_id=rfq_id,
            agent_name="TraceVault",
            action_type=f"trace_{decision}",
            message=reason,
            status="WARNING" if decision in {"reject", "freeze"} else "SUCCESS",
        ))
        await self.session.flush()
        return {
            "rfq_id": rfq_id,
            "decision": decision,
            "automation_paused": bool(payload.get("automation_paused", False)),
        }

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
