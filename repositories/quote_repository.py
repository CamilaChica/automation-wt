from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.operational_models import (
    AuditLogRecord,
    CustomerQuoteItemRecord,
    CustomerQuoteRecord,
    CommunicationTaskRecord,
    OperationalRecord,
    QuoteItemRecord,
    QuoteRecord,
    RFQRecord,
)
from services.customer_chase_schedule import chase_task_keys
from services.workflow_states import canonical_state, validate_transition


class QuoteRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_operational_record(self, domain: str, record_id: str) -> dict | None:
        record = await self.session.get(
            OperationalRecord, {"domain": domain, "record_id": record_id}
        )
        return dict(record.payload) if record else None

    async def get(self, quote_id: str) -> QuoteRecord | None:
        return await self.session.get(QuoteRecord, quote_id)

    async def for_rfq(self, rfq_id: str) -> list[QuoteRecord]:
        result = await self.session.scalars(select(QuoteRecord).where(QuoteRecord.rfq_id == rfq_id))
        return list(result)

    async def list_operational_records(self, domain: str) -> dict[str, dict]:
        result = await self.session.scalars(
            select(OperationalRecord).where(OperationalRecord.domain == domain)
        )
        return {record.record_id: dict(record.payload) for record in result}

    async def create(self, **values) -> QuoteRecord:
        record = QuoteRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def add_item(self, **values) -> QuoteItemRecord:
        record = QuoteItemRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def set_status(self, quote_id: str, status: str) -> QuoteRecord | None:
        record = await self.get(quote_id)
        if record is None:
            return None
        record.status = status
        await self.session.flush()
        return record

    async def approve_for_dispatch(
        self,
        *,
        quote_id: str,
        rfq_id: str,
        expected_version: int,
        operator_name: str,
        comments: str | None,
        quote_payload: dict,
        item_payloads: list[dict],
        override_audit_messages: list[str],
    ) -> bool:
        result = await self.session.scalars(
            select(OperationalRecord)
            .where(OperationalRecord.domain == "quotes", OperationalRecord.record_id == quote_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        quote_record = result.first()
        if quote_record is None:
            return False
        current_quote = dict(quote_record.payload)
        if current_quote.get("rfq_id") != rfq_id:
            return False
        if current_quote.get("status") in {"Approved", "Pending_Dispatch", "Dispatch_Pending", "Sent"}:
            return False
        current_version = int(current_quote.get("version") or 1)
        if current_version != expected_version:
            raise ValueError(f"Quote {quote_id} was updated by another operation.")

        item_result = await self.session.scalars(
            select(OperationalRecord)
            .where(
                OperationalRecord.domain == "quote_items",
                OperationalRecord.payload["quote_id"].as_string() == quote_id,
            )
            .with_for_update()
        )
        item_records = {record.record_id: record for record in item_result}
        if set(item_records) != {str(item["id"]) for item in item_payloads}:
            return False
        for payload in item_payloads:
            item_record = item_records[str(payload["id"])]
            item_record.payload = payload
            relational_item = await self.session.get(QuoteItemRecord, str(payload["id"]))
            if relational_item is not None:
                relational_item.unit_price = float(payload.get("unit_price") or 0)
                relational_item.details = dict(payload)

        quote_payload = dict(quote_payload)
        quote_payload.update({
            "status": "Approved",
            "approved_by": operator_name,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "version": current_version + 1,
        })
        if comments:
            quote_payload["comments"] = comments
        quote_record.payload = quote_payload

        relational_quote = await self.session.get(QuoteRecord, quote_id)
        if relational_quote is not None:
            relational_quote.status = "Approved"
            relational_quote.total_amount = float(quote_payload.get("total_amount") or 0)
        customer_quote = await self.session.get(CustomerQuoteRecord, quote_id)
        if customer_quote is not None:
            customer_quote.status = "Approved"
            customer_quote.total_price = float(quote_payload.get("total_amount") or 0)
        customer_items = await self.session.scalars(
            select(CustomerQuoteItemRecord).where(CustomerQuoteItemRecord.quote_id == quote_id)
        )
        prices = {
            (str(item.get("part_number") or "").upper(), int(item.get("quantity") or 0)): float(item.get("unit_price") or 0)
            for item in item_payloads
        }
        for customer_item in customer_items:
            key = (customer_item.part_number.upper(), customer_item.quantity)
            if key in prices:
                customer_item.unit_price = prices[key]

        for message in override_audit_messages:
            self.session.add(AuditLogRecord(
                rfq_id=rfq_id,
                agent_name="Orchestrator",
                action_type="human_override",
                message=message,
                status="SUCCESS",
            ))
        self.session.add(AuditLogRecord(
            rfq_id=rfq_id,
            agent_name="Orchestrator",
            action_type="human_approval",
            message=f"Quote {quote_id} approved by commercial operator '{operator_name}'."
            + (f" Comments: {comments}" if comments else ""),
            status="SUCCESS",
        ))
        await self.session.flush()
        return True

    async def finalize_outbox_delivery(
        self, quote_id: str, *, delivered: bool, error: str | None = None
    ) -> bool:
        quote_result = await self.session.scalars(
            select(OperationalRecord)
            .where(OperationalRecord.domain == "quotes", OperationalRecord.record_id == quote_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        quote_record = quote_result.first()
        if quote_record is None:
            return False
        quote = dict(quote_record.payload)
        rfq_id = str(quote.get("rfq_id") or "")
        rfq_result = await self.session.scalars(
            select(OperationalRecord)
            .where(OperationalRecord.domain == "rfqs", OperationalRecord.record_id == rfq_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        rfq_record = rfq_result.first()
        if rfq_record is None:
            return False
        rfq = dict(rfq_record.payload)

        quote_status = "Sent" if delivered else "Pending_Internal_Review"
        rfq_status = "Quote_Sent" if delivered else "Pending_Internal_Review"
        quote["status"] = quote_status
        quote["version"] = int(quote.get("version") or 1) + 1
        if error and not delivered:
            quote["comments"] = str(error)[:1000]
        quote_record.payload = quote
        relational_quote = await self.session.get(QuoteRecord, quote_id)
        if relational_quote is not None:
            relational_quote.status = quote_status
        customer_quote = await self.session.get(CustomerQuoteRecord, quote_id)
        if customer_quote is not None:
            customer_quote.status = quote_status

        eligible_rfq_statuses = {
            "Quote_Generation", "Pending_Approval", "Pending_Approval_Low_Margin",
            "Quote_Dispatch_Pending",
        }
        if rfq.get("status") in eligible_rfq_statuses:
            validate_transition(str(rfq["status"]), rfq_status)
            rfq["status"] = rfq_status
            rfq["workflow_state"] = canonical_state(rfq_status)
            rfq["version"] = int(rfq.get("version") or 1) + 1
            rfq_record.payload = rfq
            relational_rfq = await self.session.get(RFQRecord, rfq_id)
            if relational_rfq is not None:
                relational_rfq.status = rfq_status

        if not delivered:
            followup_tasks = await self.session.scalars(
                select(CommunicationTaskRecord)
                .where(CommunicationTaskRecord.task_key.in_(chase_task_keys(quote_id)))
                .with_for_update()
            )
            for task in followup_tasks:
                if task.status == "pending":
                    task.status = "cancelled"

        self.session.add(AuditLogRecord(
            rfq_id=rfq_id,
            agent_name="CustomerCommunicationAgent",
            action_type="email_dispatch" if delivered else "email_dispatch_manual_review",
            message=(
                "Sales proposal email successfully sent."
                if delivered
                else f"Quote email delivery requires manual verification: {str(error or 'unknown outcome')[:900]}"
            ),
            status="SUCCESS" if delivered else "WARNING",
        ))
        await self.session.flush()
        return True
