"""Long-running shared mailbox poller for the MVP deployment."""

import logging
import os
import json
import time
import asyncio
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from services.mailbox_service import fetch_inbox_messages
from services.inbound_email_archive import archive_inbound_message
from services.inbound_message_classifier import classify_inbound_customer_message
from services.communication_service import communication_service
from services.supplier_database import supplier_db
from services.db_service import db_service
from services.orchestration_service import orchestration_service
from services.document_parser import build_email_context
from scripts.backup_sqlite import main as backup_sqlite
from services.operations_store import operations_store
from services.async_database import preflight_database

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("winged-tycoons-email-worker")


def _review_inbound_customer_message(message: dict[str, Any], reason: str, rfq_id: str | None = None) -> None:
    message_id = str(message.get("internet_message_id") or message.get("message_id") or "unknown")
    operations_store.enqueue_operator_review(
        idempotency_key=f"customer-email-review:{message_id}",
        task="customer_email_classification",
        source_text=f"Subject: {message.get('subject', '')}\n\n{message.get('body', '')}",
        extraction={"category": "manual_review", "rfq_id": rfq_id},
        reason=reason,
        prompt_version="customer-email-routing-v1",
        hold_flags=[reason],
        entity_id=rfq_id or message_id,
    )


def _record_email_purchase_order(message: dict[str, Any], rfq: Any, quote: Any, po_number: str) -> dict[str, Any]:
    message_id = str(message.get("internet_message_id") or message.get("message_id") or "")
    if rfq.status in {"Pending_PO_Review", "Purchase_Order_Received"}:
        _review_inbound_customer_message(message, "additional_or_duplicate_po_requires_review", rfq.id)
        return {"status": "Pending_PO_Review", "duplicate_or_additional": True}
    quote_items = db_service.get_quote_items(quote.id)
    internal_items = []
    for item in quote_items:
        offers = (
            operations_store.get_supplier_offers(item.part_number, item.quantity)
            if operations_store.storage_engine == "postgresql"
            else supplier_db.find_supplier_offers(item.part_number, quantity_needed=item.quantity)
        )
        selected = next(
            (offer for offer in offers if abs(float(offer.get("unit_cost") or 0) - float(item.unit_cost or 0)) < 0.01),
            offers[0] if offers else None,
        )
        internal_items.append({
            "part_number": item.part_number,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "supplier_name": selected.get("supplier_name") if selected else "Internal inventory",
            "supplier_email": selected.get("supplier_email") if selected else "",
            "supplier_unit_cost": float(selected.get("unit_cost") or item.unit_cost or 0) if selected else float(item.unit_cost or 0),
        })
    attachments = [
        {"filename": str(item.get("filename") or "attachment"), "content_type": str(item.get("content_type") or ""), "size": len(item.get("content") or b"")}
        for item in message.get("attachments") or []
    ]
    transaction = operations_store.transaction() if operations_store.storage_engine == "postgresql" else nullcontext()
    with transaction:
        record = operations_store.record_purchase_order(
            po_id=f"PO-{uuid.uuid4().hex[:20].upper()}",
            po_number=po_number,
            customer_email=rfq.customer_email,
            total_amount=float(quote.total_amount or 0),
            status="Pending_PO_Review",
            quote_id=quote.id,
            rfq_id=rfq.id,
            received_message_id=message_id or None,
            attachment_metadata=attachments,
        )
        if record.get("rfq_id") and record.get("rfq_id") != rfq.id:
            _review_inbound_customer_message(message, "po_number_conflicts_with_another_rfq", rfq.id)
            return {"status": "Pending_PO_Review", "conflict": True}
        orchestration_service.mark_purchase_order_received(rfq.id, po_number, [item["filename"] for item in attachments])
        notification = communication_service.notify_purchase_order(
            recipient=os.getenv("CAMILA_NOTIFICATION_EMAIL", os.getenv("PURCHASE_ORDER_NOTIFICATION_EMAIL", "camila@wingedtycoons.com")),
            po_number=po_number,
            customer_name=rfq.customer_name,
            customer_email=rfq.customer_email,
            quote_id=quote.id,
            items=internal_items,
            review_url=os.getenv("SALES_DASHBOARD_URL") or os.getenv("PUBLIC_APP_URL", "http://localhost:3000"),
        )
    return {"status": "Pending_PO_Review", "po_number": po_number, "quote_id": quote.id, "notification": notification}


def _mailboxes_to_poll() -> list[str]:
    """The email worker owns customer RFQs; supplier mail belongs to ingestion worker."""
    return ["sales"]


async def _ingest_sales_message(message: dict[str, str]) -> bool:
    """Create and process a customer RFQ received by the sales mailbox."""
    sender = (message.get("from") or "").strip()
    if "@" not in sender:
        logger.warning("Sales message %s has no valid sender; skipped", message.get("message_id", "unknown"))
        return False
    if sender.lower() == "sales@wingedtycoons.com":
        logger.warning("Ignoring self-sent sales mailbox message %s subject=%s", message.get("message_id", "unknown"), message.get("subject", ""))
        return True
    body = (message.get("body") or "").strip()
    attachments = message.get("attachments") or []
    if not body and not attachments:
        return True
    sender_email = sender.lower()
    existing = next(
        (
            candidate for candidate in reversed(db_service.list_rfqs())
            if candidate.customer_email.lower() == sender_email
            and candidate.status in {"Quote_Sent", "Pending_PO_Review", "Purchase_Order_Received"}
        ),
        None,
    )
    quote = db_service.get_quote_by_rfq(existing.id) if existing else None
    if quote:
        communication_service.cancel_customer_followups(quote.id)
    classification = classify_inbound_customer_message(message, has_related_quote=bool(quote))
    if classification["category"] == "purchase_order":
        if not existing or not quote:
            _review_inbound_customer_message(message, "email_po_could_not_be_linked_to_an_active_quote")
            return True
        po_number = classification["po_number"] or f"PO-EMAIL-{uuid.uuid5(uuid.NAMESPACE_URL, str(message.get('internet_message_id') or message.get('message_id'))).hex[:12].upper()}"
        _record_email_purchase_order(message, existing, quote, str(po_number))
        logger.info("Email PO %s routed for review against RFQ %s", po_number, existing.id)
        return True
    if classification["category"] == "client_question":
        try:
            response = communication_service.send_customer_information_response(
                recipient=sender,
                customer_name=existing.customer_name,
                quote_id=quote.id,
                request_text=body,
                reply_to=message.get("message_id") or existing.thread_id,
            )
            db_service.add_audit_log(
                existing.id,
                "CustomerCommunicationAgent",
                "customer_detail_response",
                "Sent a customer response using only facts from the approved quote.",
                "SUCCESS",
                json.dumps({"communication_id": response.get("communication_id")} ),
            )
        except Exception as exc:
            _review_inbound_customer_message(message, f"customer_question_needs_review:{type(exc).__name__}", existing.id)
        return True
    if classification["category"] == "other":
        _review_inbound_customer_message(message, "inbound_message_not_identified_as_an_rfq", existing.id if existing else None)
        return True
    rfq = db_service.create_rfq(
        customer_name=sender.split("@", 1)[0].replace(".", " ").title(),
        customer_email=sender,
        raw_text=build_email_context(f"From: {sender}\nSubject: {message.get('subject', '')}\n\n{body}", attachments),
        thread_id=message.get("message_id") or None,
    )
    pipeline_result = await orchestration_service.process_rfq_pipeline(rfq.id)
    logger.info(
        "Sales mailbox message %s ingested as RFQ %s pipeline_status=%s quote_id=%s error=%s",
        message.get("message_id", "unknown"),
        rfq.id,
        pipeline_result.get("status", "unknown"),
        pipeline_result.get("quote_id", ""),
        pipeline_result.get("error", ""),
    )
    return True


def run() -> None:
    if operations_store.storage_engine == "postgresql":
        asyncio.run(preflight_database())
    interval = int(os.getenv("MAILBOX_POLL_INTERVAL_SECONDS", "60"))
    fetch_limit = int(os.getenv("MAILBOX_FETCH_LIMIT", "100"))
    backup_interval = int(os.getenv("SQLITE_BACKUP_INTERVAL_SECONDS", "86400"))
    last_backup_at = 0.0
    while True:
        now = time.time()
        if now - last_backup_at >= backup_interval:
            try:
                backup_sqlite()
                last_backup_at = now
                logger.info("SQLite backup completed at %s", datetime.now(timezone.utc).isoformat())
            except Exception:
                logger.exception("SQLite backup failed")

        due_tasks = (
            operations_store.list_due_communication_tasks()
            if operations_store.storage_engine == "postgresql"
            else supplier_db.list_due_communication_tasks()
        )
        for task in due_tasks:
            try:
                result = communication_service.process_due_task(task)
                if result["transmission_status"] == "SENT":
                    if operations_store.storage_engine == "postgresql":
                        operations_store.update_communication_task(task["id"], status="sent")
                    else:
                        supplier_db.mark_communication_task_sent(task["id"])
                    logger.info("Sent scheduled %s communication to %s", task["task_type"], task["recipient"])
                elif result["transmission_status"] == "PENDING" and operations_store.storage_engine == "postgresql":
                    logger.info("Queued scheduled %s communication to %s in transactional outbox", task["task_type"], task["recipient"])
                else:
                    logger.info("Dry-run scheduled %s communication retained for delivery", task["task_type"])
            except Exception:
                if operations_store.storage_engine == "postgresql":
                    operations_store.retry_communication_task(task["id"], "scheduled communication dispatch failed")
                else:
                    supplier_db.mark_communication_task_retry(task["id"], "scheduled communication dispatch failed")
                logger.exception("Scheduled communication failed for task %s", task["id"])

        for mailbox in _mailboxes_to_poll():
            try:
                messages = fetch_inbox_messages(mailbox, limit=fetch_limit)
                logger.info("Mailbox %s: read %d message bodies", mailbox, len(messages))
                for message in messages:
                    message_id = str(message.get("message_id") or "").strip()
                    internet_message_id = str(message.get("internet_message_id") or "").strip() or None
                    postgres_mode = operations_store.storage_engine == "postgresql"
                    body = (message.get("body") or "").strip()
                    if not body and not message.get("attachments"):
                        continue
                    if message_id and not postgres_mode and not operations_store.claim_inbound_message(message_id, mailbox, internet_message_id):
                        logger.info(
                            "Mailbox %s skipped duplicate message %s internet_message_id=%s from=%s subject=%s",
                            mailbox,
                            message_id,
                            internet_message_id or "none",
                            message.get("from", ""),
                            message.get("subject", ""),
                        )
                        continue
                    if postgres_mode and message_id:
                        with operations_store.transaction():
                            if not operations_store.claim_inbound_message(message_id, mailbox, internet_message_id):
                                logger.info("Mailbox %s skipped PostgreSQL-claimed message %s", mailbox, message_id)
                                continue
                            archive_inbound_message(message, mailbox)
                            processed = asyncio.run(_ingest_sales_message(message))
                            if processed:
                                operations_store.mark_inbound_message_processed(message_id, internet_message_id)
                            else:
                                operations_store.release_inbound_message(message_id, internet_message_id)
                    else:
                        try:
                            archive_inbound_message(message, mailbox)
                            processed = asyncio.run(_ingest_sales_message(message))
                            if message_id and processed:
                                operations_store.mark_inbound_message_processed(message_id, internet_message_id)
                            elif message_id:
                                operations_store.release_inbound_message(message_id, internet_message_id)
                        except Exception:
                            if message_id:
                                operations_store.release_inbound_message(message_id, internet_message_id)
                            raise
                        if message_id and processed:
                            supplier_db.save_email(mailbox, message_id, message.get("from", ""), message.get("subject", ""), body)
            except Exception:
                logger.exception("Mailbox poll failed for %s", mailbox)
        time.sleep(interval)


if __name__ == "__main__":
    run()
