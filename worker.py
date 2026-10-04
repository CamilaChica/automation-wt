"""Long-running shared mailbox poller for the MVP deployment."""

import logging
import os
import json
import time
import asyncio
import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Any

from dotenv import load_dotenv

_process_database_url = os.getenv("DATABASE_URL")
load_dotenv()
if _process_database_url is None:
    os.environ.pop("DATABASE_URL", None)
from services.database_safety import validate_development_database_target

validate_development_database_target(
    os.getenv("DATABASE_URL", ""), os.getenv("WT_ENV", os.getenv("WT_AUTH_ENV", "development"))
)

from services.mailbox_service import fetch_inbox_messages, html_to_text
from services.inbound_email_archive import _received_at, archive_inbound_message
from services.inbound_message_classifier import classify_inbound_customer_message
from services.customer_reply_routing import (
    build_resurfaced_quote_text,
    company_name_for_sender,
    find_recent_valid_quote,
    find_rfq_for_reply,
)
from services.email_intelligence import analyze_communication_sentiment
from services.communication_service import communication_service
from services.supplier_database import supplier_db
from services.db_service import db_service
from services.orchestration_service import orchestration_service
from services.document_parser import build_email_context
from scripts.backup_sqlite import main as backup_sqlite
from services.operations_store import operations_store
from services.async_database import create_engine_from_environment, preflight_database, session_scope
from repositories.runtime import create_operational_repositories
from repositories.review_telemetry_repository import inbound_dedupe_key

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("winged-tycoons-email-worker")


async def queue_due_communication_tasks(engine=None) -> dict[str, int]:
    owns_engine = engine is None
    if engine is None:
        engine = create_engine_from_environment()
    queued = 0
    failed = 0
    try:
        async with session_scope(engine) as session:
            repositories = create_operational_repositories(session)
            tasks = await repositories.records.list_due_communication_tasks()
            for task in tasks:
                try:
                    async with session.begin_nested():
                        result = await communication_service.process_due_task_async(repositories, task)
                    if result["transmission_status"] == "CANCELLED":
                        continue
                    queued += result["transmission_status"] == "PENDING"
                except Exception as exc:
                    await repositories.records.retry_communication_task(
                        task["id"], f"{type(exc).__name__}: {exc}"
                    )
                    failed += 1
                    logger.exception("Async scheduled communication queue failed for task %s", task["id"])
    finally:
        if owns_engine:
            await engine.dispose()
    return {"queued": queued, "failed": failed}


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
            attachments=[
                {
                    "filename": str(attachment.get("filename") or "purchase-order-attachment"),
                    "content_type": str(attachment.get("content_type") or "application/octet-stream"),
                    "content": attachment.get("content"),
                }
                for attachment in message.get("attachments") or []
            ],
        )
    return {"status": "Pending_PO_Review", "po_number": po_number, "quote_id": quote.id, "notification": notification}


def _mailboxes_to_poll() -> list[str]:
    """The email worker owns customer RFQs; supplier mail belongs to ingestion worker."""
    return ["sales"]


def _reply_to_rfq_update(message: dict[str, Any], rfq, sender: str, body: str) -> None:
    """Keep customer replies on their original RFQ and answer them in the same thread."""
    inbound_id = str(message.get("internet_message_id") or message.get("message_id") or uuid.uuid4().hex)
    customer_name = company_name_for_sender(db_service.list_rfqs(), sender) if "@" in sender else rfq.customer_name
    try:
        db_service.add_audit_log(
            rfq.id,
            "CustomerCommunicationAgent",
            "customer_additional_info",
            (body or "")[:4000],
            "SUCCESS",
            json.dumps({"inbound_message_id": inbound_id, "subject": message.get("subject", "")}),
        )
    except Exception as exc:
        logger.warning("customer_additional_info_audit_failed rfq=%s error=%s", rfq.id, type(exc).__name__)
    try:
        communication_service.send_rfq_update_reply(
            recipient=sender,
            customer_name=customer_name,
            rfq_id=rfq.id,
            customer_text=body,
            original_subject=str(message.get("subject") or ""),
            reply_to=message.get("message_id") or rfq.thread_id,
            inbound_message_id=inbound_id,
        )
    except Exception as exc:
        logger.warning("customer_update_reply_failed rfq=%s error=%s", rfq.id, type(exc).__name__)
        _review_inbound_customer_message(message, f"customer_update_reply_failed:{type(exc).__name__}", rfq.id)


async def _ingest_sales_message(message: dict[str, str]) -> bool:
    """Create and process a customer RFQ received by the sales mailbox."""
    sender = (message.get("from") or "").strip()
    if "@" not in sender:
        logger.warning("Sales message %s has no valid sender; skipped", message.get("message_id", "unknown"))
        return False
    if sender.lower() == "sales@wingedtycoons.com":
        logger.warning("Ignoring self-sent sales mailbox message %s subject=%s", message.get("message_id", "unknown"), message.get("subject", ""))
        return True
    body = html_to_text(message.get("body") or "")
    attachments = message.get("attachments") or []
    if not body and not attachments:
        return True
    sender_email = sender.lower()
    all_rfqs = db_service.list_rfqs()
    existing = find_rfq_for_reply(all_rfqs, sender_email, message.get("subject", ""), body)
    quote = db_service.get_quote_by_rfq(existing.id) if existing else None
    if quote:
        communication_service.cancel_customer_followups(quote.id)

    communication_sentiment = None
    if quote:
        sentiment_source = f"Subject: {message.get('subject', '')}\n\n{body}"
        sentiment_result = await asyncio.to_thread(
            analyze_communication_sentiment,
            sentiment_source,
        )
        if sentiment_result:
            communication_sentiment = sentiment_result.model_dump()
            message_id = str(
                message.get("internet_message_id")
                or message.get("message_id")
                or f"customer-email-{uuid.uuid4().hex}"
            )
            try:
                operations_store.record_automation_event(
                    event_type="inbound_communication_sentiment",
                    entity_type="email",
                    entity_id=message_id,
                    status=sentiment_result.label.upper(),
                    result=json.dumps(communication_sentiment),
                    idempotency_key=f"communication-sentiment:{message_id}",
                )
            except Exception as exc:
                logger.warning(
                    "customer_sentiment_persist_failed message_id=%s error=%s detail=%s",
                    message_id,
                    type(exc).__name__,
                    exc,
                )

    classification = classify_inbound_customer_message(message, has_related_quote=bool(quote))
    if classification["category"] == "purchase_order":
        if not existing or not quote:
            _review_inbound_customer_message(message, "email_po_could_not_be_linked_to_an_active_quote")
            return True
        po_number = classification["po_number"] or f"PO-EMAIL-{uuid.uuid5(uuid.NAMESPACE_URL, str(message.get('internet_message_id') or message.get('message_id'))).hex[:12].upper()}"
        _record_email_purchase_order(message, existing, quote, str(po_number))
        logger.info("Email PO %s routed for review against RFQ %s", po_number, existing.id)
        return True
    if existing and not quote:
        _reply_to_rfq_update(message, existing, sender, body)
        return True
    if classification["category"] == "client_question":
        try:
            response = communication_service.send_customer_information_response(
                recipient=sender,
                customer_name=existing.customer_name,
                quote_id=quote.id,
                request_text=body,
                reply_to=message.get("message_id") or existing.thread_id,
                communication_sentiment=communication_sentiment,
            )
            db_service.add_audit_log(
                existing.id,
                "CustomerCommunicationAgent",
                "customer_detail_response",
                "Sent a customer response using only facts from the approved quote.",
                "SUCCESS",
                json.dumps({
                    "communication_id": response.get("communication_id"),
                    "communication_sentiment": communication_sentiment,
                }),
            )
        except Exception as exc:
            if "requested_document_unavailable_from_verified_supplier_source" in str(exc):
                communication_service.send_customer_document_unavailable(
                    recipient=sender,
                    customer_name=existing.customer_name,
                    quote_id=quote.id,
                    reply_to=message.get("message_id") or existing.thread_id,
                )
            else:
                _reply_to_rfq_update(message, existing, sender, body)
            _review_inbound_customer_message(message, f"customer_question_needs_review:{type(exc).__name__}", existing.id)
        return True
    if classification["category"] == "other":
        if existing:
            _reply_to_rfq_update(message, existing, sender, body)
        _review_inbound_customer_message(message, "inbound_message_not_identified_as_an_rfq", existing.id if existing else None)
        return True
    if _resend_existing_quote_sync(message, all_rfqs, (parseaddr(sender)[1] or sender).lower(), body):
        return True
    rfq = db_service.create_rfq(
        customer_name=company_name_for_sender(all_rfqs, sender_email),
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


def _resend_existing_quote_sync(message: dict[str, Any], all_rfqs, sender: str, body: str) -> bool:
    try:
        quotes, items = [], []
        for rfq in all_rfqs:
            quote = db_service.get_quote_by_rfq(rfq.id)
            if quote is not None:
                quotes.append(quote)
                items.extend(db_service.get_quote_items(quote.id))
        text = f"{message.get('subject') or ''}\n{body}"
        match = find_recent_valid_quote(all_rfqs, quotes, items, sender, text, window=_duplicate_window())
        if match is None:
            return False
        rfq, quote, matched, qty_changed = match
        inbound_id = str(message.get("internet_message_id") or message.get("message_id") or uuid.uuid4().hex)
        db_service.add_audit_log(
            rfq.id, "CustomerCommunicationAgent", "duplicate_request_shield",
            f"Repeat request matched valid quote {quote.id}; re-sent instead of opening a new RFQ.",
            "SUCCESS", json.dumps({"inbound_message_id": inbound_id, "quote_id": quote.id, "qty_changed": qty_changed}),
        )
        communication_service.send_rfq_update_reply(
            recipient=sender,
            customer_name=company_name_for_sender(all_rfqs, sender),
            rfq_id=rfq.id,
            customer_text=body,
            original_subject=str(message.get("subject") or ""),
            reply_to=str(message.get("message_id") or "") or rfq.thread_id,
            inbound_message_id=inbound_id,
            quote_answer=build_resurfaced_quote_text(quote, matched, qty_changed),
        )
        return True
    except Exception as exc:
        logger.warning("duplicate_request_shield_sync_failed error=%s", type(exc).__name__)
        return False


async def _reply_to_rfq_update_async(message: dict[str, Any], rfq, sender: str, body: str, rfqs, repositories) -> None:
    inbound_id = str(message.get("internet_message_id") or message.get("message_id") or uuid.uuid4().hex)
    await repositories.rfq.add_audit_log(
        rfq_id=rfq.id,
        agent_name="CustomerCommunicationAgent",
        action_type="customer_additional_info",
        message=(body or "")[:4000],
        status="SUCCESS",
        payload_json=json.dumps({"inbound_message_id": inbound_id, "subject": message.get("subject", "")}),
    )
    await communication_service.send_rfq_update_reply_async(
        repositories,
        recipient=sender,
        customer_name=company_name_for_sender(rfqs, sender),
        rfq_id=rfq.id,
        customer_text=body,
        original_subject=str(message.get("subject") or ""),
        reply_to=str(message.get("message_id") or "") or rfq.thread_id,
        inbound_message_id=inbound_id,
    )


async def _ingest_existing_sales_message_async(message: dict[str, Any], repositories) -> bool | None:
    from models.db_models import Quote, QuoteItem

    sender_header = str(message.get("from") or "").strip()
    sender = (parseaddr(sender_header)[1] or sender_header).lower()
    message_id = str(message.get("message_id") or message.get("internet_message_id") or "")
    body = html_to_text(str(message.get("body") or ""))
    rfqs = await db_service.list_rfqs_async(repositories)
    existing = find_rfq_for_reply(rfqs, sender, str(message.get("subject") or ""), body)
    quote = None
    quote_items = []
    if existing is not None:
        quote_payloads = await repositories.quote.list_operational_records("quotes")
        quote = next((
            Quote.model_validate(payload)
            for payload in quote_payloads.values()
            if payload.get("rfq_id") == existing.id
        ), None)
        if quote is not None:
            item_payloads = await repositories.quote.list_operational_records("quote_items")
            quote_items = [
                QuoteItem.model_validate(payload)
                for payload in item_payloads.values()
                if payload.get("quote_id") == quote.id
            ]

    if quote is not None:
        await communication_service.cancel_customer_followups_async(repositories, quote.id)

    classification = classify_inbound_customer_message(message, has_related_quote=bool(quote))
    category = classification.get("category")
    if category == "purchase_order":
        message_key = str(message.get("internet_message_id") or message_id or sender)
        if existing is None or quote is None:
            reason = "email_po_could_not_be_linked_to_an_active_quote"
        elif existing.status in {"Pending_PO_Review", "Purchase_Order_Received"}:
            reason = "additional_or_duplicate_po_requires_review"
        else:
            po_number = classification.get("po_number") or (
                f"PO-EMAIL-{uuid.uuid5(uuid.NAMESPACE_URL, message_key).hex[:12].upper()}"
            )
            attachment_metadata = [
                {
                    "filename": str(attachment.get("filename") or "attachment"),
                    "content_type": str(attachment.get("content_type") or ""),
                    "size": len(attachment.get("content") or b""),
                }
                for attachment in message.get("attachments") or []
            ]
            received = await repositories.rfq.receive_purchase_order(
                po_id=f"PO-{uuid.uuid4().hex[:20].upper()}",
                po_number=str(po_number),
                received_message_id=message_key,
                quote_id=quote.id,
                rfq_id=existing.id,
                customer_email=existing.customer_email,
                total_amount=float(quote.total_amount or 0),
                attachment_metadata=attachment_metadata,
            )
            if received:
                internal_items = []
                for item in quote_items:
                    offers = await repositories.supplier.offers_for_part(
                        item.part_number, item.quantity
                    )
                    selected = next(
                        (
                            offer for offer in offers
                            if abs(float(offer.get("unit_cost") or 0) - float(item.unit_cost or 0)) < 0.01
                        ),
                        offers[0] if offers else None,
                    )
                    internal_items.append({
                        "part_number": item.part_number,
                        "quantity": item.quantity,
                        "unit_price": item.unit_price,
                        "supplier_name": selected.get("supplier_name") if selected else "Internal inventory",
                        "supplier_email": selected.get("supplier_email") if selected else "",
                        "supplier_unit_cost": (
                            float(selected.get("unit_cost") or item.unit_cost or 0)
                            if selected else float(item.unit_cost or 0)
                        ),
                    })
                await communication_service.notify_purchase_order_async(
                    repositories,
                    recipient=os.getenv(
                        "CAMILA_NOTIFICATION_EMAIL",
                        os.getenv("PURCHASE_ORDER_NOTIFICATION_EMAIL", "camila@wingedtycoons.com"),
                    ),
                    po_number=str(po_number),
                    customer_name=existing.customer_name,
                    customer_email=existing.customer_email,
                    quote_id=quote.id,
                    items=internal_items,
                    review_url=os.getenv("SALES_DASHBOARD_URL") or os.getenv("PUBLIC_APP_URL", "http://localhost:3000"),
                    attachments=[
                        {
                            "filename": str(attachment.get("filename") or "purchase-order-attachment"),
                            "content_type": str(attachment.get("content_type") or "application/octet-stream"),
                            "content": attachment.get("content"),
                        }
                        for attachment in message.get("attachments") or []
                    ],
                )
                return True
            reason = "email_po_conflicts_with_existing_purchase_order"

        await repositories.records.enqueue_operator_review(
            idempotency_key=f"customer-email-review:{message_key}",
            task="customer_email_classification",
            source_text=f"Subject: {message.get('subject', '')}\\n\\n{body}",
            extraction={"category": "manual_review", "rfq_id": existing.id if existing else None},
            reason=reason,
            prompt_version="customer-email-routing-v1",
            hold_flags=[reason],
            entity_id=existing.id if existing else message_key,
        )
        return True
    if existing is not None and quote is None:
        await _reply_to_rfq_update_async(message, existing, sender, body, rfqs, repositories)
        return True
    if category == "client_question":
        if existing is None or quote is None:
            reason = "customer_question_has_no_related_quote"
        else:
            try:
                response = await communication_service.send_customer_information_response_async(
                    repositories,
                    recipient=sender,
                    customer_name=existing.customer_name,
                    quote_id=quote.id,
                    request_text=body,
                    quote=quote,
                    items=quote_items,
                    reply_to=message_id or existing.thread_id,
                )
                await repositories.rfq.add_audit_log(
                    rfq_id=existing.id,
                    agent_name="CustomerCommunicationAgent",
                    action_type="customer_detail_response",
                    message="Queued a customer response using only facts from the approved quote.",
                    status="PENDING",
                    payload_json=json.dumps({"communication_id": response.get("communication_id")}),
                )
                return True
            except Exception as exc:
                reason = f"customer_question_needs_review:{type(exc).__name__}"
                if "requested_document_unavailable_from_verified_supplier_source" in str(exc):
                    await communication_service.send_customer_document_unavailable_async(
                        repositories,
                        recipient=sender,
                        customer_name=existing.customer_name,
                        quote_id=quote.id,
                        reply_to=message_id or existing.thread_id,
                    )
                else:
                    await _reply_to_rfq_update_async(message, existing, sender, body, rfqs, repositories)
        await repositories.records.enqueue_operator_review(
            idempotency_key=f"customer-email-review:{message_id or sender}",
            task="customer_email_classification",
            source_text=f"Subject: {message.get('subject', '')}\n\n{body}",
            extraction={"category": "manual_review", "rfq_id": existing.id if existing else None},
            reason=reason,
            prompt_version="customer-email-routing-v1",
            hold_flags=[reason],
            entity_id=existing.id if existing else message_id or sender,
        )
        return True
    if category == "other":
        reason = "inbound_message_not_identified_as_an_rfq"
        if existing is not None:
            await _reply_to_rfq_update_async(message, existing, sender, body, rfqs, repositories)
        await repositories.records.enqueue_operator_review(
            idempotency_key=f"customer-email-review:{message_id or sender}",
            task="customer_email_classification",
            source_text=f"Subject: {message.get('subject', '')}\n\n{body}",
            extraction={"category": "manual_review", "rfq_id": existing.id if existing else None},
            reason=reason,
            prompt_version="customer-email-routing-v1",
            hold_flags=[reason],
            entity_id=existing.id if existing else message_id or sender,
        )
        return True
    return None


def _duplicate_window() -> timedelta:
    try:
        return timedelta(days=max(0, int(os.getenv("DUPLICATE_REQUEST_WINDOW_DAYS", "30"))))
    except ValueError:
        return timedelta(days=30)


def _validated(model, payloads) -> list:
    records = []
    for payload in payloads:
        try:
            records.append(model.model_validate(payload))
        except Exception:
            continue
    return records


async def _resend_existing_quote_async(message: dict[str, Any], repositories) -> bool:
    """Duplicate Request Shield: re-send a still-valid quote instead of opening a new RFQ."""
    from models.db_models import Quote, QuoteItem

    sender_header = str(message.get("from") or "").strip()
    sender = (parseaddr(sender_header)[1] or sender_header).lower()
    body = html_to_text(str(message.get("body") or ""))
    text = f"{message.get('subject') or ''}\n{body}"
    try:
        rfqs = await db_service.list_rfqs_async(repositories)
        quotes = _validated(Quote, (await repositories.quote.list_operational_records("quotes")).values())
        items = _validated(QuoteItem, (await repositories.quote.list_operational_records("quote_items")).values())
        match = find_recent_valid_quote(rfqs, quotes, items, sender, text, window=_duplicate_window())
    except Exception as exc:
        logger.warning("duplicate_request_shield_lookup_failed error=%s", type(exc).__name__)
        return False
    if match is None:
        return False
    rfq, quote, matched, qty_changed = match
    inbound_id = str(message.get("internet_message_id") or message.get("message_id") or uuid.uuid4().hex)
    await repositories.rfq.add_audit_log(
        rfq_id=rfq.id,
        agent_name="CustomerCommunicationAgent",
        action_type="duplicate_request_shield",
        message=f"Repeat request matched valid quote {quote.id}; re-sent instead of opening a new RFQ.",
        status="SUCCESS",
        payload_json=json.dumps({"inbound_message_id": inbound_id, "quote_id": quote.id, "qty_changed": qty_changed}),
    )
    await communication_service.send_rfq_update_reply_async(
        repositories,
        recipient=sender,
        customer_name=company_name_for_sender(rfqs, sender),
        rfq_id=rfq.id,
        customer_text=body,
        original_subject=str(message.get("subject") or ""),
        reply_to=str(message.get("message_id") or "") or rfq.thread_id,
        inbound_message_id=inbound_id,
        quote_answer=build_resurfaced_quote_text(quote, matched, qty_changed),
    )
    logger.info("duplicate_request_shield rfq=%s quote=%s", rfq.id, quote.id)
    return True


async def _ingest_new_sales_message_async(message: dict[str, Any], repositories) -> Any:
    sender_header = str(message.get("from") or "").strip()
    sender = (parseaddr(sender_header)[1] or sender_header).lower()
    if "@" not in sender:
        raise ValueError("Sales mailbox message has no valid sender.")
    raw_text = build_email_context(
        f"From: {sender}\nSubject: {message.get('subject', '')}\n\n{str(message.get('body') or '').strip()}",
        message.get("attachments") or [],
    )
    rfqs = await db_service.list_rfqs_async(repositories)
    rfq = await db_service.create_rfq_async(
        repositories,
        customer_name=company_name_for_sender(rfqs, sender),
        customer_email=sender,
        raw_text=raw_text,
        thread_id=message.get("message_id") or None,
    )
    return rfq


async def _process_sales_message_async(
    message: dict[str, Any], mailbox: str = "sales", engine=None
) -> bool:
    owns_engine = engine is None
    engine = engine or create_engine_from_environment()
    message_id = str(message.get("message_id") or "").strip()
    try:
        async with session_scope(engine) as session:
            repositories = create_operational_repositories(session)
            internet_message_id = str(message.get("internet_message_id") or "").strip() or None
            if message_id and not await repositories.records.claim_inbound_message(
                message_id, mailbox, internet_message_id
            ):
                return True
            sender_header = str(message.get("from") or "")
            provider_message_id = message_id or str(message.get("internet_message_id") or uuid.uuid4().hex)
            attachments = [
                {
                    "filename": str(attachment.get("filename") or "attachment"),
                    "content_type": str(attachment.get("content_type") or ""),
                    "size": len(attachment.get("content") or b""),
                }
                for attachment in message.get("attachments") or []
            ]
            await repositories.records.archive_raw_email(
                mailbox=mailbox,
                provider_message_id=provider_message_id,
                internet_message_id=message.get("internet_message_id"),
                conversation_id=message.get("conversation_id"),
                sender=parseaddr(sender_header)[1] or sender_header or None,
                subject=str(message.get("subject") or "") or None,
                received_at=_received_at(message.get("date")),
                body=str(message.get("body") or ""),
                raw_mime=message.get("raw_mime"),
                headers=message.get("headers") or [],
                attachments=attachments,
                processing_status="processing",
            )
            processed = await _ingest_existing_sales_message_async(message, repositories)
            if processed is not None:
                if message_id:
                    if processed:
                        await repositories.records.mark_inbound_message_processed(
                            message_id, internet_message_id
                        )
                    else:
                        await repositories.records.release_inbound_message(
                            message_id, internet_message_id
                        )
                if processed:
                    await repositories.records.set_raw_email_processing_status(
                        mailbox, provider_message_id, "processed"
                    )
                return processed
            if await _resend_existing_quote_async(message, repositories):
                if message_id:
                    await repositories.records.mark_inbound_message_processed(
                        message_id, internet_message_id
                    )
                await repositories.records.set_raw_email_processing_status(
                    mailbox, provider_message_id, "processed"
                )
                return True
            rfq = await _ingest_new_sales_message_async(message, repositories)
            stable_message_key = inbound_dedupe_key(internet_message_id) or message_id or rfq.id
            await repositories.records.record_automation_event(
                event_type="process_new_rfq",
                entity_type="rfq",
                entity_id=rfq.id,
                status="QUEUED",
                result=json.dumps({"source_message_id": stable_message_key}),
                idempotency_key=f"rfq-intake:{stable_message_key}",
                max_attempts=3,
            )
            if message_id:
                await repositories.records.mark_inbound_message_processed(
                    message_id, internet_message_id
                )
            await repositories.records.set_raw_email_processing_status(
                mailbox, provider_message_id, "processed"
            )
            logger.info(
                "Sales mailbox message %s persisted as RFQ %s with durable intake event",
                message_id or "unknown",
                rfq.id,
            )
            return True
    except Exception:
        if message_id:
            async with session_scope(engine) as session:
                repositories = create_operational_repositories(session)
                await repositories.records.release_inbound_message(
                    message_id, str(message.get("internet_message_id") or "").strip() or None
                )
        raise
    finally:
        if owns_engine:
            await engine.dispose()


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

        async_repositories_enabled = os.getenv("USE_ASYNC_REPOS", "false").strip().lower() in {"1", "true", "yes", "on"}
        if operations_store.storage_engine == "postgresql" and async_repositories_enabled:
            try:
                queue_result = asyncio.run(queue_due_communication_tasks())
                if queue_result["queued"]:
                    logger.info(
                        "Queued %d scheduled communications through the async transactional outbox",
                        queue_result["queued"],
                    )
            except Exception:
                logger.exception("Async scheduled communication poll failed")
        else:
            due_tasks = (
                operations_store.list_due_communication_tasks()
                if operations_store.storage_engine == "postgresql"
                else supplier_db.list_due_communication_tasks()
            )
            for task in due_tasks:
                try:
                    result = communication_service.process_due_task(task)
                    if result["transmission_status"] == "CANCELLED":
                        continue
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
                    body = html_to_text(message.get("body") or "")
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
                    if postgres_mode and async_repositories_enabled:
                        processed = asyncio.run(_process_sales_message_async(message, mailbox))
                    elif postgres_mode and message_id:
                        with operations_store.transaction():
                            if not operations_store.claim_inbound_message(message_id, mailbox, internet_message_id):
                                logger.info("Mailbox %s skipped PostgreSQL-claimed message %s", mailbox, message_id)
                                continue
                            archive_inbound_message(message, mailbox)
                            try:
                                processed = asyncio.run(_ingest_sales_message(message))
                            except Exception:
                                operations_store.release_inbound_message(message_id, internet_message_id)
                                raise
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
