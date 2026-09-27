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
from typing import Any, Callable

from services.async_database import create_engine_from_environment, preflight_database, session_scope, upsert_aviation_part, upsert_supplier_quote
from services.document_parser import build_email_context
from services.mailbox_service import fetch_inbox_messages
from services.inbound_email_archive import archive_inbound_message
from services.supplier_database import supplier_db
from services.supplier_email_loader import SupplierEmailLoader
from services.supplier_inventory_importer import import_inventory_attachments
from services.negotiation_service import SupplierNegotiationService
from services.communication_service import communication_service
from services.operations_store import operations_store

logger = logging.getLogger("winged-tycoons-inventory-ingestion")


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
        from services.db_service import db_service

        for rfq in db_service.list_rfqs():
            if rfq.status != "Supplier_Sourcing":
                continue
            if not any(
                (item.resolved_part_number or item.requested_part_number).upper() == part_number.upper()
                for item in db_service.get_rfq_items(rfq.id)
            ):
                continue
            event_id = operations_store.record_automation_event(
                event_type="resume_waiting_rfq",
                entity_type="rfq",
                entity_id=rfq.id,
                status="QUEUED",
                result=json.dumps({"part_number": part_number.upper()}),
                idempotency_key=f"rfq-resume:{rfq.id}:{part_number.upper()}",
                max_attempts=3,
            )
            logger.info("Queued RFQ resume event=%s rfq=%s part=%s", event_id, rfq.id, part_number)

    def process_message(self, message: dict[str, Any]) -> dict[str, Any]:
        if operations_store.storage_engine == "postgresql":
            with operations_store.transaction():
                return self._process_message(message)
        return self._process_message(message)

    def _process_message(self, message: dict[str, Any]) -> dict[str, Any]:
        message_id = str(message.get("message_id") or "").strip()
        internet_message_id = str(message.get("internet_message_id") or "").strip() or None
        postgres_mode = operations_store.storage_engine == "postgresql"
        body = str(message.get("body") or "").strip()
        if not body and not message.get("attachments"):
            return {"success": False, "skipped": True, "error": "Message has no body or attachments."}

        if postgres_mode and message_id:
            with operations_store.transaction():
                if not operations_store.claim_inbound_message(message_id, self.mailbox, internet_message_id):
                    return {"success": True, "skipped": True, "message_id": message_id}
                archive_inbound_message(message, self.mailbox)
                result = import_inventory_attachments(message, self.mailbox)
                if result is None:
                    result = self.loader.load_raw_email_text(
                        self._email_text(message),
                        mailbox=self.mailbox,
                        message_id=message_id,
                        attachments=message.get("attachments") or [],
                    )
                if (
                    result.get("success")
                    or result.get("status") == "Pending_Human_Review"
                    or "No part number detected" in str(result.get("error", ""))
                ):
                    operations_store.mark_inbound_message_processed(message_id, internet_message_id)
                else:
                    operations_store.release_inbound_message(message_id, internet_message_id)
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
                )
            if message_id:
                if result.get("success") or result.get("status") == "Pending_Human_Review" or "No part number detected" in str(result.get("error", "")):
                    operations_store.mark_inbound_message_processed(message_id, internet_message_id)
                else:
                    operations_store.release_inbound_message(message_id, internet_message_id)
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
            self.poll_once()
            elapsed = time.monotonic() - started
            time.sleep(max(0, self.poll_interval_seconds - elapsed))


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    InventoryIngestionWorker().run_forever()
