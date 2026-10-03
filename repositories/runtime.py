from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.async_models import PurchaseOrder
from models.operational_models import (
    AutomationEventRecord,
    CommunicationRecord,
    CommunicationTaskRecord,
    LLMTelemetryRecord,
    OperationalRecord,
    OutboxMessageRecord,
    InboundMessageIdempotencyRecord,
    InboundEmailRecord,
    OperatorReviewRecord,
    NegotiationSessionRecord,
    RawEmailRecord,
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
from repositories.review_telemetry_repository import inbound_dedupe_key


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

    async def list_purchase_orders(self, status: str) -> list[dict]:
        result = await self.rfq.session.execute(
            select(
                PurchaseOrder.id,
                PurchaseOrder.po_number,
                PurchaseOrder.customer_email,
                PurchaseOrder.total_amount,
                PurchaseOrder.status,
                PurchaseOrder.quote_id,
                PurchaseOrder.rfq_id,
                PurchaseOrder.attachment_metadata,
                PurchaseOrder.created_at,
            )
            .where(PurchaseOrder.status == status)
            .order_by(PurchaseOrder.created_at.asc())
        )
        return [dict(row) for row in result.mappings().all()]


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

    async def claim_inbound_message(
        self, message_id: str, mailbox: str, internet_message_id: str | None = None
    ) -> bool:
        keys = [message_id]
        stable_key = inbound_dedupe_key(internet_message_id)
        if stable_key and stable_key not in keys:
            keys.append(stable_key)
        claimed: list[str] = []
        for key in keys:
            statement = postgres_insert(InboundMessageIdempotencyRecord).values(
                message_id=key, mailbox=mailbox, status="processing"
            ).on_conflict_do_nothing(
                index_elements=[InboundMessageIdempotencyRecord.message_id]
            ).returning(InboundMessageIdempotencyRecord.message_id)
            inserted = await self.session.scalar(statement)
            if inserted is None:
                if claimed:
                    await self.session.execute(
                        delete(InboundMessageIdempotencyRecord).where(
                            InboundMessageIdempotencyRecord.message_id.in_(claimed),
                            InboundMessageIdempotencyRecord.status == "processing",
                        )
                    )
                return False
            claimed.append(key)
        return True

    async def mark_inbound_message_processed(
        self, message_id: str, internet_message_id: str | None = None
    ) -> None:
        keys = [message_id]
        stable_key = inbound_dedupe_key(internet_message_id)
        if stable_key and stable_key not in keys:
            keys.append(stable_key)
        records = await self.session.scalars(
            select(InboundMessageIdempotencyRecord).where(
                InboundMessageIdempotencyRecord.message_id.in_(keys)
            )
        )
        for record in records:
            record.status = "processed"
            record.processed_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def release_inbound_message(
        self, message_id: str, internet_message_id: str | None = None
    ) -> None:
        keys = [message_id]
        stable_key = inbound_dedupe_key(internet_message_id)
        if stable_key and stable_key not in keys:
            keys.append(stable_key)
        await self.session.execute(
            delete(InboundMessageIdempotencyRecord).where(
                InboundMessageIdempotencyRecord.message_id.in_(keys),
                InboundMessageIdempotencyRecord.status == "processing",
            )
        )

    async def cancel_communication_task(self, task_key: str) -> None:
        tasks = list(await self.session.scalars(
            select(CommunicationTaskRecord).where(
                CommunicationTaskRecord.task_key == task_key
            ).with_for_update()
        ))
        for task in tasks:
            if task.status == "pending":
                task.status = "cancelled"
        task_ids = [task.id for task in tasks]
        if task_ids:
            await self.session.execute(
                update(OutboxMessageRecord)
                .where(
                    OutboxMessageRecord.communication_task_id.in_(task_ids),
                    OutboxMessageRecord.status == "PENDING",
                )
                .values(
                    status="CANCELLED",
                    error_message="Customer activity cancelled the scheduled follow-up",
                )
            )
        await self.session.flush()

    async def archive_raw_email(self, **values) -> None:
        message_id = str(values["provider_message_id"])
        raw_email_key = f"{values['mailbox']}:{message_id}"
        raw_email_id = f"RAW-{uuid.uuid5(uuid.NAMESPACE_URL, raw_email_key).hex[:24].upper()}"
        statement = postgres_insert(RawEmailRecord).values(
            id=raw_email_id,
            **values,
        ).on_conflict_do_update(
            index_elements=[RawEmailRecord.mailbox, RawEmailRecord.provider_message_id],
            set_={
                "internet_message_id": values.get("internet_message_id"),
                "conversation_id": values.get("conversation_id"),
                "sender": values.get("sender"),
                "subject": values.get("subject"),
                "received_at": values.get("received_at"),
                "body": values.get("body") or "",
                "raw_mime": values.get("raw_mime"),
                "headers": values.get("headers") or [],
                "attachments": values.get("attachments") or [],
                "processing_status": values.get("processing_status") or "received",
            },
        )
        await self.session.execute(statement)

    async def set_raw_email_processing_status(
        self, mailbox: str, provider_message_id: str, status: str
    ) -> None:
        record = await self.session.scalar(
            select(RawEmailRecord)
            .where(
                RawEmailRecord.mailbox == mailbox,
                RawEmailRecord.provider_message_id == provider_message_id,
            )
            .with_for_update()
        )
        if record is not None:
            record.processing_status = status
            await self.session.flush()

    async def get_negotiation_session(self, supplier_email: str, part_number: str) -> dict | None:
        record = await self.session.scalar(
            select(NegotiationSessionRecord).where(
                NegotiationSessionRecord.supplier_email == supplier_email.strip().lower(),
                NegotiationSessionRecord.part_number == part_number.strip().upper(),
            )
        )
        return dict(record.payload) if record else None

    async def save_negotiation_session(
        self, *, session_id: str, supplier_email: str, part_number: str, payload: dict
    ) -> None:
        statement = postgres_insert(NegotiationSessionRecord).values(
            id=session_id,
            supplier_email=supplier_email.strip().lower(),
            part_number=part_number.strip().upper(),
            payload=payload,
        ).on_conflict_do_update(
            index_elements=[NegotiationSessionRecord.supplier_email, NegotiationSessionRecord.part_number],
            set_={"payload": payload, "updated_at": func.now()},
        )
        await self.session.execute(statement)

    async def save_inbound_email(self, **values) -> None:
        message_id = str(values["message_id"])
        statement = postgres_insert(InboundEmailRecord).values(
            id=f"IN-{uuid.uuid5(uuid.NAMESPACE_URL, message_id).hex[:24].upper()}",
            message_id=message_id,
            mailbox=values["mailbox"],
            sender=values.get("sender"),
            subject=values.get("subject"),
            body=values.get("body") or "",
            processing_status=values.get("processing_status") or "processed",
            extraction_error=values.get("extraction_error"),
        ).on_conflict_do_update(
            index_elements=[InboundEmailRecord.message_id],
            set_={
                "mailbox": values["mailbox"],
                "sender": values.get("sender"),
                "subject": values.get("subject"),
                "body": values.get("body") or "",
                "processing_status": values.get("processing_status") or "processed",
                "extraction_error": values.get("extraction_error"),
            },
        )
        await self.session.execute(statement)

    async def enqueue_operator_review(self, **values) -> str:
        review_id = f"REV-{uuid.uuid4().hex[:12].upper()}"
        statement = postgres_insert(OperatorReviewRecord).values(
            id=review_id,
            idempotency_key=values["idempotency_key"],
            task=values["task"],
            prompt_version=values.get("prompt_version"),
            entity_id=values.get("entity_id"),
            source_text=values["source_text"],
            extraction_json=json.dumps(values["extraction"]),
            reason=values["reason"],
            hold_flags_json=json.dumps(values.get("hold_flags") or []),
            status="PENDING",
        ).on_conflict_do_nothing(
            index_elements=[OperatorReviewRecord.idempotency_key]
        ).returning(OperatorReviewRecord.id)
        inserted_id = await self.session.scalar(statement)
        if inserted_id is not None:
            return str(inserted_id)
        existing_id = await self.session.scalar(
            select(OperatorReviewRecord.id).where(
                OperatorReviewRecord.idempotency_key == values["idempotency_key"]
            )
        )
        if existing_id is None:
            raise RuntimeError("Operator review could not be inserted or found after idempotency conflict.")
        return str(existing_id)

    async def upsert(self, domain: str, record_id: str, payload: dict) -> None:
        record = await self.session.get(
            OperationalRecord, {"domain": domain, "record_id": record_id}
        )
        if record is None:
            record = OperationalRecord(domain=domain, record_id=record_id, payload=payload)
            self.session.add(record)
        else:
            record.payload = payload
        await self.session.flush()

    async def enqueue_outbox_message(
        self,
        *,
        deduplication_key: str,
        mailbox: str,
        recipient: str,
        subject: str,
        body: str,
        reply_to: str | None = None,
        communication_task_id: str | None = None,
        entity_id: str | None = None,
        max_retries: int = 5,
    ) -> dict:
        statement = (
            postgres_insert(OutboxMessageRecord)
            .values(
                id=f"OUT-{uuid.uuid4().hex[:16].upper()}",
                deduplication_key=deduplication_key,
                entity_id=entity_id,
                mailbox=mailbox,
                recipient=recipient,
                subject=subject,
                payload={"body": body},
                reply_to=reply_to,
                communication_task_id=communication_task_id,
                status="PENDING",
                retry_count=0,
                max_retries=max(1, int(max_retries)),
            )
            .on_conflict_do_nothing(index_elements=[OutboxMessageRecord.deduplication_key])
            .returning(
                OutboxMessageRecord.id,
                OutboxMessageRecord.status,
                OutboxMessageRecord.retry_count,
                OutboxMessageRecord.created_at,
            )
        )
        row = (await self.session.execute(statement)).mappings().one_or_none()
        if row is None:
            row = (await self.session.execute(
                select(
                    OutboxMessageRecord.id,
                    OutboxMessageRecord.status,
                    OutboxMessageRecord.retry_count,
                    OutboxMessageRecord.created_at,
                ).where(OutboxMessageRecord.deduplication_key == deduplication_key)
            )).mappings().one()
        return dict(row)

    async def record_llm_telemetry(self, **values) -> None:
        self.session.add(LLMTelemetryRecord(
            id=f"LLM-{uuid.uuid4().hex[:12].upper()}",
            task=values["task"],
            prompt_version=values["prompt_version"],
            model_id=values["model_id"],
            model_calls_json=json.dumps(values.get("model_calls") or []),
            latency_ms=max(float(values.get("latency_ms") or 0), 0.0),
            input_tokens=max(int(values.get("input_tokens") or 0), 0),
            output_tokens=max(int(values.get("output_tokens") or 0), 0),
            estimated_cost_usd=max(float(values.get("estimated_cost_usd") or 0), 0.0),
            validation_result=values["validation_result"],
            review_queue_id=values.get("review_queue_id"),
        ))
        await self.session.flush()

    async def record_automation_event(self, **values) -> None:
        event_id = f"AUT-{uuid.uuid4().hex[:12].upper()}"
        statement = (
            postgres_insert(AutomationEventRecord)
            .values(
                id=event_id,
                idempotency_key=values.get("idempotency_key"),
                event_type=values["event_type"],
                entity_type=values["entity_type"],
                entity_id=values["entity_id"],
                status=values["status"],
                attempts=int(values.get("attempts") or 0),
                max_attempts=max(1, int(values.get("max_attempts") or 3)),
                execution_time=None,
                result=values.get("result"),
                error=values.get("error"),
            )
            .on_conflict_do_nothing(index_elements=[AutomationEventRecord.idempotency_key])
        )
        await self.session.execute(statement)

    async def schedule_communication_task(self, **values) -> dict:
        task_id = f"TASK-{uuid.uuid4().hex[:16].upper()}"
        statement = (
            postgres_insert(CommunicationTaskRecord)
            .values(
                id=task_id,
                task_key=values["task_key"],
                task_type=values.get("task_type") or "email",
                mailbox=values.get("mailbox") or "sales",
                recipient=values["recipient"],
                subject=values["subject"],
                body=values["body"],
                reply_to=values.get("reply_to"),
                due_at=values["due_at"],
                status="pending",
                attempts=0,
                max_attempts=max(1, int(values.get("max_attempts") or 5)),
            )
            .on_conflict_do_nothing(index_elements=[CommunicationTaskRecord.task_key])
            .returning(CommunicationTaskRecord.id, CommunicationTaskRecord.task_key, CommunicationTaskRecord.status)
        )
        row = (await self.session.execute(statement)).mappings().one_or_none()
        if row is None:
            row = (await self.session.execute(
                select(
                    CommunicationTaskRecord.id,
                    CommunicationTaskRecord.task_key,
                    CommunicationTaskRecord.status,
                ).where(CommunicationTaskRecord.task_key == values["task_key"])
            )).mappings().one()
        return dict(row)

    async def list_due_communication_tasks(self, *, limit: int = 100) -> list[dict]:
        result = await self.session.scalars(
            select(CommunicationTaskRecord)
            .where(
                CommunicationTaskRecord.status == "pending",
                CommunicationTaskRecord.due_at <= func.now(),
            )
            .order_by(CommunicationTaskRecord.due_at, CommunicationTaskRecord.id)
            .limit(min(max(int(limit), 1), 100))
        )
        return [{
            "id": task.id,
            "task_key": task.task_key,
            "task_type": task.task_type,
            "mailbox": task.mailbox,
            "recipient": task.recipient,
            "subject": task.subject,
            "body": task.body,
            "reply_to": task.reply_to,
            "attempts": task.attempts,
            "max_attempts": task.max_attempts,
        } for task in result]

    async def retry_communication_task(self, task_id: str, error: str) -> None:
        task = await self.session.scalar(
            select(CommunicationTaskRecord)
            .where(CommunicationTaskRecord.id == task_id)
            .with_for_update()
        )
        if task is None or task.status != "pending":
            return
        task.attempts += 1
        task.status = "dead_letter" if task.attempts >= task.max_attempts else "pending"
        task.last_error = str(error)[:1000]
        if task.status == "pending":
            task.due_at = datetime.now(timezone.utc) + timedelta(
                seconds=min(3600, 5 * (2 ** max(task.attempts - 1, 0)))
            )
        await self.session.flush()

    async def claim_outbox_messages(self, *, limit: int = 25) -> list[dict]:
        records = await self.session.scalars(
            select(OutboxMessageRecord)
            .where(
                OutboxMessageRecord.status == "PENDING",
                OutboxMessageRecord.available_at <= func.now(),
            )
            .order_by(OutboxMessageRecord.created_at, OutboxMessageRecord.id)
            .with_for_update(skip_locked=True)
            .limit(min(max(int(limit), 1), 100))
        )
        now = datetime.now(timezone.utc)
        claimed = []
        for record in records:
            record.status = "SENDING"
            record.retry_count += 1
            record.sending_started_at = now
            claimed.append({
                "id": record.id,
                "deduplication_key": record.deduplication_key,
                "entity_id": record.entity_id,
                "mailbox": record.mailbox,
                "recipient": record.recipient,
                "subject": record.subject,
                "payload": dict(record.payload or {}),
                "reply_to": record.reply_to,
                "communication_task_id": record.communication_task_id,
                "retry_count": record.retry_count,
                "max_retries": record.max_retries,
            })
        await self.session.flush()
        return claimed

    async def mark_outbox_sent(self, message_id: str) -> bool:
        message = await self.session.get(
            OutboxMessageRecord, message_id, with_for_update=True
        )
        if message is None or message.status != "SENDING":
            return False
        message.status = "SENT"
        message.sent_at = datetime.now(timezone.utc)
        message.sending_started_at = None
        message.error_message = None
        if message.communication_task_id:
            task = await self.session.get(
                CommunicationTaskRecord, message.communication_task_id, with_for_update=True
            )
            if task is not None:
                task.status = "sent"
                task.sent_at = message.sent_at
                task.attempts += 1
        await self.session.flush()
        return True

    async def fail_outbox_message(
        self, message_id: str, error: str, *, retryable: bool = False
    ) -> str:
        message = await self.session.get(
            OutboxMessageRecord, message_id, with_for_update=True
        )
        if message is None or message.status != "SENDING":
            return "MANUAL_REVIEW_REQUIRED"
        can_retry = retryable and message.retry_count < message.max_retries
        message.status = "PENDING" if can_retry else "MANUAL_REVIEW_REQUIRED"
        message.error_message = str(error)[:2000]
        message.sending_started_at = None
        message.available_at = datetime.now(timezone.utc) + timedelta(
            seconds=min(3600, 5 * (2 ** max(message.retry_count - 1, 0)))
        )
        if message.communication_task_id:
            task = await self.session.get(
                CommunicationTaskRecord, message.communication_task_id, with_for_update=True
            )
            if task is not None:
                task.status = "pending" if can_retry else "manual_review_required"
                task.attempts += 1
                task.last_error = str(error)[:1000]
        await self.session.flush()
        return message.status

    async def recover_stale_outbox_messages(self, *, sending_timeout_seconds: int = 300) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(1, int(sending_timeout_seconds)))
        records = await self.session.scalars(
            select(OutboxMessageRecord)
            .where(
                OutboxMessageRecord.status == "SENDING",
                OutboxMessageRecord.sending_started_at < cutoff,
            )
            .with_for_update(skip_locked=True)
        )
        recovered = list(records)
        for message in recovered:
            message.status = "MANUAL_REVIEW_REQUIRED"
            message.sending_started_at = None
            message.error_message = "Delivery outcome unknown after stale SENDING lease; manual verification required"
            if message.communication_task_id:
                task = await self.session.get(
                    CommunicationTaskRecord, message.communication_task_id, with_for_update=True
                )
                if task is not None:
                    task.status = "manual_review_required"
                    task.last_error = "Outbox delivery outcome unknown; manual verification required"
        await self.session.flush()
        return len(recovered)

    async def record_communication(self, **values) -> str:
        communication_id = f"COM-{uuid.uuid4().hex[:12].upper()}"
        self.session.add(CommunicationRecord(
            id=communication_id,
            entity_type=values.get("entity_type") or "email",
            entity_id=str(values["entity_id"]),
            recipient=values["recipient"],
            sender=values["sender"],
            channel=values.get("channel") or "email",
            subject=values.get("subject") or "",
            message=values.get("message") or "",
            message_type=values.get("message_type") or "outbound",
            status=values["status"],
            sent_at=datetime.now(timezone.utc) if values["status"] == "SENT" else None,
        ))
        await self.session.flush()
        return communication_id

    async def has_domain(self, domain: str) -> bool:
        record_id = await self.session.scalar(
            select(OperationalRecord.record_id)
            .where(OperationalRecord.domain == domain)
            .limit(1)
        )
        return record_id is not None

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