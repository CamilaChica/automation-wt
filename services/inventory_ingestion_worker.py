"""Continuous supplier-mail inventory ingestion worker.

The worker is intentionally separate from the API process. It performs bounded
polls, uses message-id idempotency, parses attachment text, and optionally
mirrors normalized records into PostgreSQL when DATABASE_URL is configured.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any, Callable

from services.async_database import create_engine_from_environment, preflight_database, session_scope, upsert_aviation_part, upsert_supplier_quote
from services.document_parser import build_email_context
from services.mailbox_service import fetch_inbox_messages
from services.inbound_email_archive import archive_inbound_message, _received_at
from services.supplier_database import supplier_db
from services.supplier_email_loader import SupplierEmailLoader
from services.supplier_inventory_importer import (
    has_inventory_table_attachments,
    import_inventory_attachments,
    import_inventory_attachments_async,
)
from services.negotiation_service import SupplierNegotiationService
from services.communication_service import communication_service
from services.operations_store import operations_store

logger = logging.getLogger("winged-tycoons-inventory-ingestion")

WAITING_STATUSES = (
    "Supplier_Sourcing",
    "No_Quote",
    "Supplier_Confirmation_Requested",
)


class _NullSavepoint:
    def commit(self):
        pass

    def rollback(self):
        pass


class InventoryIngestionWorker:
    def __init__(
        self,
        *,
        fetch_messages: Callable[..., list[dict[str, Any]]] = fetch_inbox_messages,
        loader: SupplierEmailLoader | None = None,
    ):
        self.fetch_messages = fetch_messages
        self.loader = loader or SupplierEmailLoader()
        self.negotiation_service = SupplierNegotiationService()
        self.mailbox = os.getenv("INVENTORY_INGESTION_MAILBOX", "purchasing")
        self.poll_interval_seconds = int(os.getenv("INVENTORY_INGESTION_POLL_INTERVAL_SECONDS", "60"))
        # Historical backfill walks the whole purchasing inbox page by page so older supplier quotes
        # and inventory lists are loaded too; the default fetcher is the only one that supports paging.
        self.backfill_enabled = (
            fetch_messages is fetch_inbox_messages
            and os.getenv("INVENTORY_INGESTION_BACKFILL_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        )
        self.backfill_days = int(os.getenv("INVENTORY_INGESTION_BACKFILL_DAYS", "3650"))
        self.backfill_page_size = int(os.getenv("INVENTORY_INGESTION_BACKFILL_PAGE_SIZE", "25"))
        self.backfill_offset = 0
        self.backfill_stats: dict[str, Any] | None = None
        self.backfill_progress_loaded = False
        self.backfill_complete = False
        self.backfill_force = os.getenv("INVENTORY_INGESTION_BACKFILL_FORCE", "false").strip().lower() in {"1", "true", "yes", "on"}
        explicit_postgres = os.getenv("INVENTORY_INGESTION_POSTGRES_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.postgres_enabled = bool(os.getenv("DATABASE_URL", "").strip()) and explicit_postgres

    @staticmethod
    def _email_text(message: dict[str, Any]) -> str:
        header = (
            f"From: {message.get('from', '')}\n"
            f"Subject: {message.get('subject', '')}\n\n"
            f"{message.get('body', '')}"
        )
        return build_email_context(header, message.get("attachments"))

    async def _persist_postgres(self, result: dict[str, Any], message: dict[str, Any]) -> None:
        if not self.postgres_enabled or not result.get("success") or result.get("imports"):
            return
        engine = create_engine_from_environment()
        try:
            async with session_scope(engine) as session:
                part = await upsert_aviation_part(
                    session,
                    part_number=str(result["part_number"]),
                    description=str(result.get("description") or "Supplier-provided aviation part"),
                    condition_code=result.get("condition_code") or "NE",
                    unit_price=result.get("unit_cost"),
                    currency="USD",
                    warranty_terms=result.get("warranty_terms"),
                    lead_time_days=int(result.get("lead_time_days") or 0),
                )
                await upsert_supplier_quote(
                    session,
                    supplier_email=str(result.get("supplier_email") or message.get("from") or "unknown@example.com"),
                    part_id=part.id,
                    quoted_price=result.get("unit_cost"),
                    raw_email_id=result.get("source_email_id"),
                    has_trace_docs=bool(result.get("trace_documents") or result.get("certificate_type")),
                    quantity_available=result.get("quantity_available"),
                    condition_code=result.get("condition_code"),
                    certificate_type=result.get("certificate_type"),
                    lead_time_days=result.get("lead_time_days"),
                    availability_location=result.get("availability_location"),
                    warranty_terms=result.get("warranty_terms"),
                    trace_documents=json.dumps(result.get("trace_documents") or []),
                )
        finally:
            await engine.dispose()

    def _enqueue_waiting_rfqs(self, part_number: str) -> None:
        if not part_number:
            return
        if operations_store.storage_engine == "postgresql":
            asyncio.run(self._enqueue_waiting_rfqs_postgres(part_number))
            return
        self._enqueue_waiting_rfqs_local(part_number)

    async def _enqueue_waiting_rfqs_postgres(self, part_number: str) -> None:
        from repositories.runtime import create_operational_repositories

        engine = create_engine_from_environment()
        try:
            async with session_scope(engine) as session:
                repositories = create_operational_repositories(session)
                rfqs = await self._waiting_rfqs(repositories)
                for rfq_id, status in rfqs:
                    item_records = await repositories.records.list_by_payload_value(
                        "rfq_items", "rfq_id", rfq_id
                    )
                    if not any(
                        str(item.get("resolved_part_number") or item.get("requested_part_number") or "").upper()
                        == part_number.upper()
                        for item in item_records.values()
                    ):
                        continue
                    if status == "No_Quote":
                        self._reopen_no_quote(rfq_id)
                    await repositories.records.record_automation_event(
                        event_type="resume_waiting_rfq",
                        entity_type="rfq",
                        entity_id=rfq_id,
                        status="QUEUED",
                        result=json.dumps({"part_number": part_number.upper()}),
                        idempotency_key=self._resume_key(rfq_id, part_number, status),
                        max_attempts=3,
                    )
        finally:
            await engine.dispose()

    async def _enqueue_waiting_rfqs_async(self, repositories, part_number: str) -> None:
        if not part_number:
            return
        rfqs = await self._waiting_rfqs(repositories)
        for rfq_id, status in rfqs:
            item_records = await repositories.records.list_by_payload_value(
                "rfq_items", "rfq_id", rfq_id
            )
            if not any(
                str(item.get("resolved_part_number") or item.get("requested_part_number") or "").upper()
                == part_number.upper()
                for item in item_records.values()
            ):
                continue
            if status == "No_Quote":
                self._reopen_no_quote(rfq_id)
            await repositories.records.record_automation_event(
                event_type="resume_waiting_rfq",
                entity_type="rfq",
                entity_id=rfq_id,
                status="QUEUED",
                result=json.dumps({"part_number": part_number.upper()}),
                idempotency_key=self._resume_key(rfq_id, part_number, status),
                max_attempts=3,
            )

    def _enqueue_waiting_rfqs_local(self, part_number: str) -> None:
        from services.db_service import db_service

        for rfq in db_service.list_rfqs():
            if rfq.status not in WAITING_STATUSES:
                continue
            if not any(
                (item.resolved_part_number or item.requested_part_number).upper() == part_number.upper()
                for item in db_service.get_rfq_items(rfq.id)
            ):
                continue
            status = rfq.status
            if status == "No_Quote":
                self._reopen_no_quote(rfq.id)
            self._record_resume_event(rfq.id, part_number, status)

    @staticmethod
    def _resume_key(rfq_id: str, part_number: str, status: str = "") -> str:
        suffix = ":reopen" if status == "No_Quote" else ""
        return f"rfq-resume:{rfq_id}:{part_number.upper()}{suffix}"

    @staticmethod
    def _reopen_no_quote(rfq_id: str) -> None:
        from services.db_service import db_service
        from services.no_quote_service import reopen_if_no_quote

        try:
            reopen_if_no_quote(db_service, rfq_id)
        except Exception:
            logger.exception("Late-offer reopen failed rfq=%s", rfq_id)

    @staticmethod
    async def _waiting_rfqs(repositories) -> list[tuple[str, str]]:
        rfqs: list[tuple[str, str]] = []
        found_records = False
        for wanted in WAITING_STATUSES:
            rfq_records = await repositories.records.list_by_payload_value("rfqs", "status", wanted)
            found_records = found_records or bool(rfq_records)
            rfqs.extend(
                (str(payload.get("id") or record_id), str(payload.get("status") or wanted))
                for record_id, payload in rfq_records.items()
            )
        if not found_records and not await repositories.records.has_domain("rfqs"):
            for wanted in WAITING_STATUSES:
                rfqs.extend(
                    (record.id, record.status) for record in await repositories.rfq.list_by_status(wanted)
                )
        return rfqs

    @classmethod
    def _record_resume_event(cls, rfq_id: str, part_number: str, status: str = "") -> None:
        event_id = operations_store.record_automation_event(
            event_type="resume_waiting_rfq",
            entity_type="rfq",
            entity_id=rfq_id,
            status="QUEUED",
            result=json.dumps({"part_number": part_number.upper()}),
            idempotency_key=cls._resume_key(rfq_id, part_number, status),
            max_attempts=3,
        )
        logger.info("Queued RFQ resume event=%s rfq=%s part=%s", event_id, rfq_id, part_number)

    def process_message(self, message: dict[str, Any]) -> dict[str, Any]:
        async_enabled = os.getenv("USE_ASYNC_REPOS", "false").strip().lower() in {"1", "true", "yes", "on"}
        if (
            self.postgres_enabled
            and async_enabled
            and has_inventory_table_attachments(message)
        ):
            return asyncio.run(self._process_inventory_table_message_async(message))
        if (
            self.postgres_enabled
            and async_enabled
            and not (message.get("attachments") or [])
        ):
            return asyncio.run(self._process_plain_supplier_message_async(message))
        if operations_store.storage_engine == "postgresql":
            with operations_store.transaction():
                return self._process_message(message)
        return self._process_message(message)

    async def _process_inventory_table_message_async(self, message: dict[str, Any], engine=None) -> dict[str, Any]:
        from repositories.runtime import create_operational_repositories

        owns_engine = engine is None
        if engine is None:
            engine = create_engine_from_environment()
        message_id = str(message.get("message_id") or "").strip()
        try:
            async with session_scope(engine) as session:
                repositories = create_operational_repositories(session)
                if message_id and not await repositories.records.claim_inbound_message(message_id, self.mailbox):
                    return {"success": True, "skipped": True, "message_id": message_id}
                if message_id:
                    attachments = [
                        {
                            "filename": str(item.get("filename") or "attachment"),
                            "content_type": str(item.get("content_type") or "application/octet-stream"),
                            "size": len(item.get("content") or b""),
                        }
                        for item in message.get("attachments") or []
                    ]
                    await repositories.records.archive_raw_email(
                        mailbox=self.mailbox,
                        provider_message_id=message_id,
                        internet_message_id=message.get("internet_message_id"),
                        conversation_id=message.get("conversation_id"),
                        sender=str(message.get("from") or "") or None,
                        subject=str(message.get("subject") or "") or None,
                        received_at=_received_at(message.get("date")),
                        body=str(message.get("body") or ""),
                        raw_mime=message.get("raw_mime"),
                        headers=message.get("headers") or [],
                        attachments=attachments,
                        processing_status="received",
                    )
                result = await import_inventory_attachments_async(message, self.mailbox, repositories)
                if result is None:
                    if message_id:
                        await repositories.records.mark_inbound_message_processed(message_id)
                    return {"success": False, "skipped": True, "message_id": message_id}
                if result.get("success"):
                    await self._record_supplier_negotiations_async(repositories, message, result)
                for part_number in result.get("part_numbers") or []:
                    await self._enqueue_waiting_rfqs_async(repositories, str(part_number))
                if message_id:
                    await repositories.records.mark_inbound_message_processed(message_id)
                return {"message_id": message_id, "result": result, "success": bool(result.get("success"))}
        except Exception as exc:
            return await self._record_failed_message_async(message, engine, exc)
        finally:
            if owns_engine:
                await engine.dispose()

    async def _record_failed_message_async(self, message: dict[str, Any], engine, exc: Exception) -> dict[str, Any]:
        from repositories.runtime import create_operational_repositories

        message_id = str(message.get("message_id") or "").strip()
        logger.exception("Inventory ingestion failed for %s; marking as failed", message_id or "unknown")
        if message_id:
            try:
                async with session_scope(engine) as session:
                    repositories = create_operational_repositories(session)
                    await repositories.records.claim_inbound_message(message_id, self.mailbox)
                    await repositories.records.archive_raw_email(
                        mailbox=self.mailbox,
                        provider_message_id=message_id,
                        internet_message_id=message.get("internet_message_id"),
                        conversation_id=message.get("conversation_id"),
                        sender=str(message.get("from") or "") or None,
                        subject=str(message.get("subject") or "") or None,
                        received_at=_received_at(message.get("date")),
                        body=str(message.get("body") or ""),
                        raw_mime=message.get("raw_mime"),
                        headers=message.get("headers") or [],
                        attachments=[],
                        processing_status="failed",
                    )
                    await repositories.records.mark_inbound_message_processed(message_id)
            except Exception:
                logger.exception("Could not record failed inventory message %s", message_id)
        return {"message_id": message_id, "success": False, "failed": True, "error": str(exc)}

    async def _process_plain_supplier_message_async(
        self, message: dict[str, Any], engine=None
    ) -> dict[str, Any]:
        message_id = str(message.get("message_id") or "").strip()
        owns_engine = engine is None
        if engine is None:
            engine = create_engine_from_environment()
        try:
            async with session_scope(engine) as session:
                from repositories.runtime import create_operational_repositories

                repositories = create_operational_repositories(session)
                if message_id and not await repositories.records.claim_inbound_message(message_id, self.mailbox):
                    return {"success": True, "skipped": True, "message_id": message_id}
                if message_id:
                    await repositories.records.archive_raw_email(
                        mailbox=self.mailbox,
                        provider_message_id=message_id,
                        internet_message_id=message.get("internet_message_id"),
                        conversation_id=message.get("conversation_id"),
                        sender=str(message.get("from") or "") or None,
                        subject=str(message.get("subject") or "") or None,
                        received_at=_received_at(message.get("date")),
                        body=str(message.get("body") or ""),
                        raw_mime=message.get("raw_mime"),
                        headers=message.get("headers") or [],
                        attachments=[],
                        processing_status="processing",
                    )
                result = await self.loader.ingestion_service.ingest_email_async(
                    self._email_text(message),
                    repositories,
                    mailbox=self.mailbox,
                    message_id=message_id or None,
                    source_received_at=_received_at(message.get("date")),
                )
                if not result.get("success") and "no part number" in str(result.get("error", "")).lower():
                    pdf_attachments = [
                        attachment for attachment in message.get("attachments") or []
                        if str(attachment.get("content_type", "")).lower() == "application/pdf"
                        or str(attachment.get("filename", "")).lower().endswith(".pdf")
                    ]
                    sender = str(message.get("from") or "").strip()
                    sender_email = parseaddr(sender)[1] or sender
                    if pdf_attachments and "@" in sender_email:
                        await communication_service.request_supplier_body_quote_async(
                            repositories,
                            recipient=sender_email,
                            part_reference=str(message.get("subject") or "supplier quotation"),
                            reply_to=message_id or message.get("internet_message_id"),
                        )
                        await repositories.records.save_inbound_email(
                            mailbox=self.mailbox,
                            message_id=message_id or str(message.get("internet_message_id") or ""),
                            sender=sender_email,
                            subject=str(message.get("subject") or ""),
                            body=self._email_text(message),
                            processing_status="clarification_sent",
                        )
                        result = {
                            **result,
                            "success": False,
                            "status": "Unreadable_PDF_Clarification_Sent",
                        }
                if result.get("success"):
                    await self._record_supplier_negotiations_async(repositories, message, result)
                successful = bool(result.get("success"))
                held_for_review = result.get("status") == "Pending_Human_Review"
                if message_id:
                    # Always advance: unparseable supplier mail must not be re-ingested every poll.
                    await repositories.records.mark_inbound_message_processed(message_id)
                    if held_for_review:
                        await repositories.records.set_raw_email_processing_status(
                            self.mailbox, message_id, "pending_human_review"
                        )
                    elif not successful:
                        await repositories.records.set_raw_email_processing_status(
                            self.mailbox, message_id, "no_inventory_data"
                        )
                if successful:
                    for item in result.get("items") or [result]:
                        await self._enqueue_waiting_rfqs_async(
                            repositories, str(item.get("part_number") or result.get("part_number") or "")
                        )
                return {"message_id": message_id, "result": result, "success": successful}
        except Exception as exc:
            return await self._record_failed_message_async(message, engine, exc)
        finally:
            if owns_engine:
                await engine.dispose()

    async def _record_supplier_negotiations_async(self, repositories, message, result) -> None:
        from email.utils import parseaddr

        sender = str(message.get("from") or "")
        sender_name, sender_email = parseaddr(sender)
        supplier_email = str(result.get("supplier_email") or sender_email or sender).strip()
        supplier_name = str(result.get("supplier_name") or sender_name or "Supplier Team")
        message_id = str(message.get("internet_message_id") or message.get("message_id") or "")
        for item in result.get("items") or []:
            await self.negotiation_service.record_supplier_quote_async(
                repositories,
                supplier_email=supplier_email,
                supplier_name=supplier_name,
                part_number=str(item.get("part_number") or result.get("part_number") or ""),
                quantity=int(item.get("quantity_available") or item.get("quantity") or 1),
                unit_cost=float(item.get("unit_cost") or item.get("unit_price") or 0),
                source_email_id=str(item.get("source_email_id") or result.get("source_email_id") or message_id),
                reply_to=message_id or None,
                supplier_sentiment=result.get("communication_sentiment"),
            )

    def _process_message(self, message: dict[str, Any]) -> dict[str, Any]:
        message_id = str(message.get("message_id") or "").strip()
        internet_message_id = str(message.get("internet_message_id") or "").strip() or None
        postgres_mode = operations_store.storage_engine == "postgresql"
        body = str(message.get("body") or "").strip()
        if not body and not message.get("attachments"):
            return {"success": False, "skipped": True, "error": "Message has no body or attachments."}

        if postgres_mode and message_id:
            with operations_store.transaction() as connection:
                if not operations_store.claim_inbound_message(message_id, self.mailbox, internet_message_id):
                    return {"success": True, "skipped": True, "message_id": message_id}
                # Savepoint keeps a failed statement from aborting the claim/release bookkeeping.
                savepoint = connection.begin_nested() if hasattr(connection, "begin_nested") else _NullSavepoint()
                try:
                    archive_inbound_message(message, self.mailbox)
                    result = import_inventory_attachments(message, self.mailbox)
                    if result is None:
                        result = self.loader.load_raw_email_text(
                            self._email_text(message),
                            mailbox=self.mailbox,
                            message_id=message_id,
                            attachments=message.get("attachments") or [],
                            source_received_at=_received_at(message.get("date")),
                        )
                except Exception:
                    savepoint.rollback()
                    raise
                # Non-quote mail is archived and marked handled so the backfill keeps advancing.
                # A helper may swallow a SQL error and leave the savepoint aborted; roll it back then.
                try:
                    if hasattr(connection, "execute"):
                        from sqlalchemy import text as _sql_text
                        connection.execute(_sql_text("SELECT 1"))
                    savepoint.commit()
                except Exception:
                    logger.warning("Ingestion savepoint aborted for %s; rolled back partial writes.", message_id)
                    savepoint.rollback()
                operations_store.mark_inbound_message_processed(message_id, internet_message_id)
        else:
            if message_id and not operations_store.claim_inbound_message(message_id, self.mailbox, internet_message_id):
                return {"success": True, "skipped": True, "message_id": message_id}
            archive_inbound_message(message, self.mailbox)
            result = import_inventory_attachments(message, self.mailbox)
            if result is None:
                result = self.loader.load_raw_email_text(
                    self._email_text(message),
                    mailbox=self.mailbox,
                    message_id=message_id or None,
                    attachments=message.get("attachments") or [],
                    source_received_at=_received_at(message.get("date")),
                )
            if message_id:
                operations_store.mark_inbound_message_processed(message_id, internet_message_id)
        if postgres_mode and message_id and result.get("status") == "Pending_Human_Review":
            operations_store.set_raw_email_processing_status(
                self.mailbox, message_id, "pending_human_review"
            )
        if not result.get("success") and "No part number detected" in str(result.get("error")):
            pdf_attachments = [
                attachment for attachment in message.get("attachments") or []
                if str(attachment.get("content_type", "")).lower() == "application/pdf"
                or str(attachment.get("filename", "")).lower().endswith(".pdf")
            ]
            sender = str(message.get("from") or "").strip()
            if pdf_attachments and "@" in sender:
                communication_service.request_supplier_body_quote(
                    recipient=sender,
                    part_reference=str(message.get("subject") or "supplier quotation"),
                    reply_to=message_id or None,
                )
                if postgres_mode:
                    operations_store.save_operational_record("inbound_emails", message_id or f"unreadable-pdf-{time.time_ns()}", {
                        "id": message_id,
                        "mailbox": self.mailbox,
                        "message_id": message_id,
                        "sender": sender,
                        "subject": str(message.get("subject") or ""),
                        "body": body,
                        "processing_status": "clarification_sent",
                    })
                else:
                    supplier_db.save_email(
                        mailbox=self.mailbox,
                        message_id=message_id or f"unreadable-pdf-{time.time_ns()}",
                        sender=sender,
                        subject=str(message.get("subject") or ""),
                        body=body,
                    )
                result = {
                    **result,
                    "success": False,
                    "status": "Unreadable_PDF_Clarification_Sent",
                }
        mirror_warning = None
        if result.get("success"):
            try:
                for item in result.get("items") or [result]:
                    item_result = {**result, **item}
                    asyncio.run(self._persist_postgres(item_result, message))
            except Exception as exc:
                mirror_warning = f"PostgreSQL mirror pending: {type(exc).__name__}"
                logger.exception("Supplier inventory mirror failed for %s", message_id or "unknown")
            sender = str(message.get("from") or "")
            supplier_email = str(result.get("supplier_email") or sender)
            if "@" in supplier_email:
                for item in result.get("items") or [result]:
                    unit_cost = item.get("unit_cost")
                    part_number = item.get("part_number") or result.get("part_number")
                    if not unit_cost or not part_number:
                        continue
                    negotiation = self.negotiation_service.record_supplier_quote(
                        supplier_email=supplier_email,
                        supplier_name=str(result.get("supplier_name") or "Supplier Team"),
                        part_number=str(part_number),
                        quantity=int(item.get("quantity_available") or result.get("quantity_available") or 1),
                        unit_cost=float(unit_cost),
                        source_email_id=str(item.get("source_email_id") or result.get("source_email_id") or message_id),
                        reply_to=message_id or None,
                        supplier_sentiment=result.get("communication_sentiment"),
                    )
                    logger.info("Supplier negotiation %s part=%s state=%s", negotiation.get("session_id", "none"), part_number, negotiation.get("status"))
            for part_number in result.get("part_numbers") or [result.get("part_number")]:
                self._enqueue_waiting_rfqs(str(part_number or ""))
        response = {"message_id": message_id, "result": result, "success": bool(result.get("success"))}
        if mirror_warning:
            response["persistence_warning"] = mirror_warning
        return response

    def poll_once(self, limit: int = 25) -> list[dict[str, Any]]:
        messages = self.fetch_messages(self.mailbox, limit=limit)
        results = self._process_batch(messages)
        if self.backfill_enabled:
            results.extend(self.backfill_once())
        return results

    def backfill_once(self, max_pages: int = 20) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        if not self.backfill_progress_loaded:
            self._load_backfill_progress()
        if self.backfill_complete and not self.backfill_force:
            return results
        if self.backfill_stats is None:
            self.backfill_stats = {
                "pages_fetched": 0,
                "messages_fetched": 0,
                "messages_processed": 0,
                "offers_extracted": 0,
                "messages_needing_review": 0,
                "messages_without_offer": 0,
                "processing_failures": 0,
                "oldest_received_at": None,
            }
        for _ in range(max_pages):
            try:
                fetch_options = {
                    "limit": self.backfill_page_size,
                    "skip": self.backfill_offset,
                    "max_age_days": self.backfill_days,
                }
                if self.fetch_messages is fetch_inbox_messages:
                    fetch_options["oldest_first"] = True
                messages = self.fetch_messages(self.mailbox, **fetch_options)
            except Exception:
                self._persist_backfill_progress("incomplete")
                logger.exception(
                    "inventory_backfill_incomplete offset=%s stats=%s",
                    self.backfill_offset,
                    json.dumps(self.backfill_stats, sort_keys=True),
                )
                return results
            if not messages:
                self._persist_backfill_progress("complete", offset=0)
                logger.info(
                    "inventory_backfill_complete mailbox=%s age_days=%s stats=%s",
                    self.mailbox,
                    self.backfill_days,
                    json.dumps(self.backfill_stats, sort_keys=True),
                )
                self.backfill_offset = 0
                self.backfill_stats = None
                self.backfill_complete = True
                return results
            logger.info("Inventory backfill offset=%s messages=%s", self.backfill_offset, len(messages))
            self.backfill_offset += len(messages)
            page = self._process_batch(messages)
            self._record_backfill_page(messages, page)
            self._persist_backfill_progress("running")
            results.extend(page)
            # Keep paging only while the page held nothing new (already ingested after a restart).
            if not all(item.get("skipped") or (item.get("result") or {}).get("skipped") for item in page):
                return results
        return results

    def _load_backfill_progress(self) -> None:
        self.backfill_progress_loaded = True
        if operations_store.storage_engine != "postgresql":
            return
        state = operations_store.get_operational_record(
            "ingestion_state", f"supplier-backfill:{self.mailbox}"
        )
        if self.backfill_force or not state or int(state.get("age_days") or 0) != self.backfill_days:
            return
        if state.get("status") == "complete":
            self.backfill_complete = True
        elif state.get("status") in {"running", "incomplete"}:
            self.backfill_offset = max(0, int(state.get("offset") or 0))
            self.backfill_stats = dict(state.get("stats") or {})
            logger.info(
                "inventory_backfill_resuming mailbox=%s offset=%s",
                self.mailbox,
                self.backfill_offset,
            )

    def _persist_backfill_progress(self, status: str, *, offset: int | None = None) -> None:
        if operations_store.storage_engine != "postgresql":
            return
        operations_store.save_operational_record(
            "ingestion_state",
            f"supplier-backfill:{self.mailbox}",
            {
                "mailbox": self.mailbox,
                "folder": "Inbox",
                "age_days": self.backfill_days,
                "status": status,
                "offset": self.backfill_offset if offset is None else offset,
                "stats": self.backfill_stats or {},
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _record_backfill_page(
        self, messages: list[dict[str, Any]], results: list[dict[str, Any]]
    ) -> None:
        stats = self.backfill_stats
        if stats is None:
            return
        stats["pages_fetched"] += 1
        stats["messages_fetched"] += len(messages)
        received_dates = [
            received_at
            for message in messages
            if (received_at := _received_at(message.get("date"))) is not None
        ]
        if received_dates:
            oldest = min(received_dates).isoformat()
            current_oldest = stats["oldest_received_at"]
            if current_oldest is None or oldest < current_oldest:
                stats["oldest_received_at"] = oldest

        for result in results:
            detail = result.get("result") or {}
            if result.get("skipped") or detail.get("skipped"):
                continue
            stats["messages_processed"] += 1
            if result.get("failed") or result.get("error"):
                stats["processing_failures"] += 1
                continue
            if detail.get("pending_human_review") or detail.get("status") == "Pending_Human_Review":
                stats["messages_needing_review"] += 1
            elif detail.get("success"):
                imports = detail.get("imports") or []
                imported_rows = sum(int(item.get("rows_imported") or 0) for item in imports)
                offers = detail.get("items") or ([detail] if detail.get("part_number") else [])
                stats["offers_extracted"] += imported_rows or len(offers)
            else:
                stats["messages_without_offer"] += 1

        logger.info(
            "inventory_backfill_progress offset=%s stats=%s",
            self.backfill_offset,
            json.dumps(stats, sort_keys=True),
        )

    def _process_batch(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results = []
        for message in messages:
            try:
                results.append(self.process_message(message))
            except Exception as exc:
                logger.exception("Inventory message processing failed: %s", message.get("message_id", "unknown"))
                results.append({"message_id": message.get("message_id", ""), "success": False, "error": str(exc)})
        return results

    def run_forever(self) -> None:
        if operations_store.storage_engine == "postgresql":
            asyncio.run(preflight_database())
        while True:
            started = time.monotonic()
            try:
                self.poll_once()
            except Exception:
                logger.exception("Inventory ingestion poll failed; retrying next interval")
            elapsed = time.monotonic() - started
            time.sleep(max(0, self.poll_interval_seconds - elapsed))


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    InventoryIngestionWorker().run_forever()
