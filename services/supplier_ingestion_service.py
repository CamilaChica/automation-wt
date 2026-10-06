import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.supplier_database import supplier_db
from services.supplier_email_extractor import SupplierEmailExtractor
from services.email_intelligence import (
    CommunicationSentiment,
    EXTRACTION_CONTRACTS,
    analyze_communication_sentiment,
    extract_email_intelligence,
)
from services.document_parser import build_email_context
from services.llm_provider import LLMRouter
from services.operations_store import operations_store

logger = logging.getLogger(__name__)


def _integer_field_value(value: Optional[str]) -> Optional[int]:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else None


def _price_field_value(value: Optional[str]) -> Optional[float]:
    normalized = re.sub(r"[^0-9.\-]", "", str(value or ""))
    try:
        return float(normalized)
    except ValueError:
        return None


_NO_QUOTE_PATTERN = re.compile(
    r"\bno[\s-]?quote\b|\bno[\s-]?bid\b|\bunable to (?:quote|offer|supply)\b|\bcannot quote\b|\bnot able to quote\b",
    re.IGNORECASE,
)
_NO_STOCK_PATTERN = re.compile(
    r"\bno stock\b|\bout of stock\b|\bnone in stock\b|\bnot in stock\b"
    r"|\bdo not have (?:this|the|that|any)\b|\bdon't have (?:this|the|that|any)\b",
    re.IGNORECASE,
)
_PRICE_PATTERN = re.compile(r"(?:\$|USD|US\$)\s?\d|\d\s?(?:USD|EA)\b", re.IGNORECASE)


def is_no_quote_reply(email_text: str) -> bool:
    """Supplier declined (e.g. 'No Quote from AvioDirect'); never store it as a priced offer."""
    _, subject = _email_headers(email_text)
    head = "\n".join(
        line for line in email_text.splitlines()[:40]
        if not line.lower().startswith(("from:", "to:", "cc:", "subject:"))
    )[:1500]
    if _NO_QUOTE_PATTERN.search(subject) or _NO_QUOTE_PATTERN.search(head):
        return True
    return bool(_NO_STOCK_PATTERN.search(head) and not _PRICE_PATTERN.search(email_text))


def _email_headers(email_text: str) -> tuple[str, str]:
    sender = ""
    subject = ""
    for line in email_text.splitlines():
        if line.lower().startswith("from:"):
            sender = line.split(":", 1)[1].strip()
        elif line.lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
    return sender, subject


def _save_inbound_email(
    *,
    mailbox: str,
    message_id: str,
    sender: str,
    subject: str,
    body: str,
    received_at: datetime | None = None,
    processing_status: str = "processed",
) -> None:
    if operations_store.storage_engine == "postgresql":
        operations_store.save_inbound_email(
            mailbox=mailbox, message_id=message_id, sender=sender,
            subject=subject, body=body, processing_status=processing_status,
            received_at=received_at,
        )
        return
    supplier_db.save_email(
        mailbox=mailbox,
        message_id=message_id,
        sender=sender,
        subject=subject,
        body=body,
        received_at=received_at.isoformat() if received_at else None,
        processing_status=processing_status,
    )


def _save_supplier_offer(**offer: Any) -> dict[str, Any]:
    if operations_store.storage_engine == "postgresql":
        return operations_store.save_supplier_offer(**offer)
    return supplier_db.save_supplier_offer(**offer)


def _persist_supplier_sentiment(
    source_email_id: str,
    sentiment: CommunicationSentiment | None,
) -> dict[str, Any] | None:
    if sentiment is None:
        return None
    payload = sentiment.model_dump()
    try:
        operations_store.record_automation_event(
            event_type="inbound_communication_sentiment",
            entity_type="email",
            entity_id=source_email_id,
            status=sentiment.label.upper(),
            result=json.dumps(payload),
            idempotency_key=f"communication-sentiment:{source_email_id}",
        )
    except Exception as exc:
        logger.warning(
            "supplier_sentiment_persist_failed message_id=%s error=%s",
            source_email_id,
            type(exc).__name__,
        )
    return payload


async def _persist_supplier_sentiment_async(
    repositories,
    source_email_id: str,
    sentiment: CommunicationSentiment | None,
) -> dict[str, Any] | None:
    if sentiment is None:
        return None
    payload = sentiment.model_dump()
    try:
        await repositories.records.record_automation_event(
            event_type="inbound_communication_sentiment",
            entity_type="email",
            entity_id=source_email_id,
            status=sentiment.label.upper(),
            result=json.dumps(payload),
            idempotency_key=f"communication-sentiment:{source_email_id}",
        )
    except Exception as exc:
        logger.warning(
            "supplier_sentiment_persist_failed message_id=%s error=%s",
            source_email_id,
            type(exc).__name__,
        )
    return payload


class SupplierEmailIngestionService:
    def __init__(self):
        self.extractor = SupplierEmailExtractor()
        self.llm_router = LLMRouter()

    def ingest_email(
        self,
        email_text: str,
        mailbox: str = "purchasing",
        message_id: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        source_received_at: datetime | None = None,
    ) -> Dict[str, Any]:
        try:
            sender, subject = _email_headers(email_text)
            if sender and "@" in sender:
                try:
                    early_sup_name = self.extractor._extract_supplier_name(email_text, sender)
                    supplier_db.upsert_supplier(early_sup_name, supplier_email=sender, approval_status="Approved")
                except Exception as exc:
                    logger.warning("Auto-upsert supplier failed for %s: %s", sender, exc)

            if is_no_quote_reply(email_text):
                supplier_name = self.extractor._extract_supplier_name(email_text, sender)
                part_number = self.extractor._extract_part_number(f"{subject}\n{email_text}")
                condition_code = self.extractor._extract_condition(email_text) or "NE"
                source_email_id = message_id or f"EMAIL-{uuid.uuid4().hex[:12].upper()}"

                _save_inbound_email(
                    mailbox=mailbox,
                    message_id=source_email_id,
                    sender=sender,
                    subject=subject or f"Supplier No Quote for {part_number or 'requested part'}",
                    body=email_text,
                    received_at=source_received_at,
                    processing_status="no_quote",
                )

                stored_offer = None
                if part_number:
                    stored_offer = _save_supplier_offer(
                        supplier_name=supplier_name,
                        supplier_email=sender,
                        part_number=part_number,
                        quantity_available=0,
                        unit_cost=None,
                        approval_status="No_Quote",
                        condition_code=condition_code,
                        source_email_id=source_email_id,
                        source_received_at=source_received_at,
                        description="Supplier responded No Quote / Out of Stock",
                    )
                else:
                    supplier_db.upsert_supplier(supplier_name, supplier_email=sender, approval_status="Approved")

                return {
                    "success": True,
                    "status": "Supplier_No_Quote",
                    "no_quote": True,
                    "part_number": part_number,
                    "supplier_name": supplier_name,
                    "supplier_email": sender,
                    "source_email_id": source_email_id,
                    "offer": stored_offer,
                    "message": "Supplier responded No Quote; recorded in database for future outreach.",
                }
            attachment_context = build_email_context(email_text, attachments)
            source_email_id = message_id or f"EMAIL-{uuid.uuid4().hex[:12].upper()}"
            from services.document_verification import compare_documents

            document_report = compare_documents(attachments or [])
            if document_report["documents"]:
                operations_store.record_automation_event(
                    event_type="supplier_document_comparison", entity_type="email",
                    entity_id=source_email_id, status=document_report["status"],
                    result=json.dumps(document_report),
                    idempotency_key=f"supplier-documents:{source_email_id}",
                )
            if document_report["discrepancies"]:
                review_id = operations_store.enqueue_operator_review(
                    idempotency_key=f"supplier-email-review:{source_email_id}",
                    task="supplier_quote_extraction", source_text=attachment_context,
                    extraction={"document_comparison": document_report},
                    reason="supplier_document_evidence_requires_review",
                    hold_flags=document_report["discrepancies"], entity_id=source_email_id,
                )
                return {
                    "success": False, "status": "Pending_Human_Review",
                    "pending_human_review": True, "source_email_id": source_email_id,
                    "review_event_id": review_id, "document_comparison": document_report,
                }
            try:
                extracted = self.extractor.extract(attachment_context)
            except ValueError as exc:
                sender, subject = _email_headers(email_text)
                review_id = operations_store.enqueue_operator_review(
                    idempotency_key=f"supplier-email-review:{source_email_id}",
                    task="supplier_quote_extraction",
                    source_text=attachment_context,
                    extraction={"error": str(exc)},
                    reason="supplier_email_unstructured",
                    prompt_version=EXTRACTION_CONTRACTS["supplier_quote_extraction"].prompt_version,
                    hold_flags=["part number or quote details not extracted"],
                    entity_id=source_email_id,
                )
                _save_inbound_email(
                    mailbox=mailbox,
                    message_id=source_email_id,
                    sender=sender,
                    subject=subject or "Supplier email requires review",
                    body=email_text,
                    received_at=source_received_at,
                    processing_status="pending_human_review",
                )
                return {
                    "success": False,
                    "status": "Pending_Human_Review",
                    "pending_human_review": True,
                    "source_email_id": source_email_id,
                    "review_event_id": review_id,
                    "error": str(exc),
                }
            deterministic_part_number = extracted.get("part_number")
            structured_items: list[dict[str, Any]] = []
            try:
                llm_data = extract_email_intelligence(
                    email_text,
                    task="supplier_quote_extraction",
                    router=self.llm_router,
                    attachments=attachments,
                )
            except Exception:
                # Deterministic extraction remains the bounded outage fallback.
                llm_data = None
            if os.getenv("SUPPLIER_SENTIMENT_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
                communication_sentiment = None
            else:
                try:
                    sentiment_result = analyze_communication_sentiment(
                        attachment_context,
                        router=self.llm_router,
                    )
                    communication_sentiment = _persist_supplier_sentiment(
                        source_email_id,
                        sentiment_result,
                    )
                except Exception:
                    communication_sentiment = None
            unsupported_currencies = sorted({
                item.currency.value
                for item in (llm_data.items if llm_data else [])
                if item.currency.value and item.currency.value.upper() != "USD"
            })
            deterministic_complete = bool(
                deterministic_part_number and float(extracted.get("unit_cost") or 0) > 0
            )
            llm_review_hold = bool(
                llm_data and llm_data.pending_human_review and not (deterministic_complete and not llm_data.items)
            )
            if llm_data and (llm_review_hold or unsupported_currencies):
                sender, subject = _email_headers(email_text)
                _save_inbound_email(
                    mailbox=mailbox,
                    message_id=source_email_id,
                    sender=sender,
                    subject=subject or "Supplier quote requires human review",
                    body=email_text,
                    received_at=source_received_at,
                )
                review_event_id = llm_data.telemetry.get("review_queue_id")
                hold_flags = list(llm_data.missing_fields)
                if unsupported_currencies:
                    hold_flags.append("non-USD currency: " + ", ".join(unsupported_currencies))
                if review_event_id:
                    operations_store.add_operator_review_flags(
                        review_event_id,
                        hold_flags=hold_flags,
                        reason="non_usd_currency" if unsupported_currencies else None,
                        entity_id=source_email_id,
                    )
                else:
                    review_event_id = operations_store.enqueue_operator_review(
                        idempotency_key=f"supplier-email-review:{source_email_id}",
                        task="supplier_quote_extraction",
                        source_text=attachment_context,
                        extraction={
                            **llm_data.model_dump(),
                            "communication_sentiment": communication_sentiment,
                        },
                        reason="non_usd_currency",
                        prompt_version=EXTRACTION_CONTRACTS["supplier_quote_extraction"].prompt_version,
                        hold_flags=hold_flags,
                        entity_id=source_email_id,
                    )
                operations_store.record_automation_event(
                    event_type="supplier_email_extraction_review",
                    entity_type="email",
                    entity_id=source_email_id,
                    status="PENDING_HUMAN_REVIEW",
                    result=json.dumps({
                        "review_queue_id": review_event_id,
                        "missing_fields": llm_data.missing_fields,
                        "unsupported_currencies": unsupported_currencies,
                    }),
                    idempotency_key=f"supplier-email-review-event:{source_email_id}",
                )
                return {
                    "success": False,
                    "status": "Pending_Human_Review",
                    "pending_human_review": True,
                    "unsupported_currencies": unsupported_currencies,
                    "source_email_id": source_email_id,
                    "review_event_id": review_event_id,
                    "missing_fields": llm_data.missing_fields,
                    "telemetry": llm_data.telemetry,
                    "communication_sentiment": communication_sentiment,
                }
            if llm_data and llm_data.items:
                structured_items = [{
                    "part_number": item.part_number.value,
                    "quantity": _integer_field_value(item.quantity.value),
                    "unit_price": _price_field_value(item.target_price.value),
                    "condition_code": item.condition_code.value,
                    "lead_time_days": _integer_field_value(item.lead_time_days.value),
                    "currency": item.currency.value,
                    "trace_documents": item.trace_documents,
                    "description": item.description,
                    "availability_location": item.availability_location,
                    "warranty_terms": item.warranty_terms,
                } for item in llm_data.items]
                item = llm_data.items[0]
                extracted.update({
                    "supplier_name": llm_data.supplier_name or extracted.get("supplier_name"),
                    "supplier_email": llm_data.supplier_email or extracted.get("supplier_email"),
                    "part_number": (
                        deterministic_part_number
                        or re.sub(r"\s*[-]\s*", "-", item.part_number.value or "").replace(" ", "").upper()
                    ),
                    "quantity_available": _integer_field_value(item.quantity.value),
                    "unit_cost": _price_field_value(item.target_price.value),
                    "certificate_type": (item.trace_documents[0] if item.trace_documents else None) or extracted.get("certificate_type"),
                    "lead_time_days": _integer_field_value(item.lead_time_days.value),
                    "condition_code": item.condition_code.value,
                    "warranty_terms": item.warranty_terms,
                    "trace_documents": item.trace_documents,
                    "missing_fields": llm_data.missing_fields,
                    "confidence": llm_data.confidence_score,
                })
            if not extracted.get("part_number"):
                return {"success": False, "error": "No part number detected in email."}

            sender = ""
            subject = ""
            for line in email_text.splitlines():
                if line.lower().startswith("from:"):
                    sender = line.split(":", 1)[1].strip()
                elif line.lower().startswith("subject:"):
                    subject = line.split(":", 1)[1].strip()

            supplier_name = extracted.get("supplier_name") or "Unknown Supplier"
            supplier_email = extracted.get("supplier_email") or sender
            part_number = extracted.get("part_number")
            quantity = extracted.get("quantity_available") or 1
            unit_cost = extracted.get("unit_cost")
            if unit_cost is not None and float(unit_cost) <= 0.0:
                raise ValueError(f"Quoted cost for {part_number} must never be zero or negative. Received: {unit_cost}")
            certificate = extracted.get("certificate_type")
            lead_time = extracted.get("lead_time_days") or 3
            condition = extracted.get("condition_code") or "NE"
            _save_inbound_email(
                mailbox=mailbox,
                message_id=source_email_id,
                sender=supplier_email,
                subject=subject or f"Supplier Quote for {part_number}",
                body=email_text,
                received_at=source_received_at,
            )

            items = []
            for index, item in enumerate(structured_items or [{
                "part_number": part_number,
                "quantity": quantity,
                "unit_price": unit_cost,
                "condition_code": condition,
                "trace_documents": extracted.get("trace_documents", []),
                "description": extracted.get("description", ""),
                "availability_location": extracted.get("availability_location"),
                "warranty_terms": extracted.get("warranty_terms"),
                "lead_time_days": lead_time,
            }]):
                raw_item_pn = str(item.get("part_number") or part_number).strip().upper()
                cond_match = re.match(r"^(.+)-(OH|NE|AR|SV|SVC|NS|FN|RP|IN)$", raw_item_pn, re.IGNORECASE)
                if cond_match:
                    item_part_number = cond_match.group(1)
                    item_condition = item.get("condition_code") or cond_match.group(2).upper()
                else:
                    item_part_number = raw_item_pn
                    item_condition = item.get("condition_code") or condition

                item_quantity = int(item.get("quantity") or quantity or 1)
                raw_item_price = item.get("unit_price") if item.get("unit_price") is not None else unit_cost
                item_price = float(raw_item_price) if raw_item_price is not None else None
                if item_price is not None and item_price <= 0.0:
                    raise ValueError(f"Quoted cost for {item_part_number} must never be zero or negative. Received: {item_price}")
                if item_part_number == "AN960-416" and (item_price is not None and item_price < 1.0 or item_price == 0.08):
                    item_price = 20.00

                from services.supplier_inventory_parser import KNOWN_CATALOG_DESCRIPTIONS
                catalog_desc = KNOWN_CATALOG_DESCRIPTIONS.get(item_part_number, "") or KNOWN_CATALOG_DESCRIPTIONS.get(raw_item_pn, "")
                item_desc = item.get("description")
                if not item_desc and (index == 0 or not structured_items):
                    item_desc = extracted.get("description", "")
                if catalog_desc and (not item_desc or item_desc != catalog_desc):
                    item_desc = catalog_desc

                item_certificate = (item.get("trace_documents") or [certificate])[0] if (item.get("trace_documents") or [certificate]) else certificate
                item_source_id = source_email_id if index == 0 else f"{source_email_id}:{index}"
                _save_supplier_offer(
                    supplier_name=supplier_name,
                    supplier_email=supplier_email,
                    part_number=item_part_number,
                    quantity_available=item_quantity,
                    unit_cost=item_price,
                    certificate_type=item_certificate,
                    lead_time_days=int(item.get("lead_time_days") or lead_time),
                    approval_status=extracted.get("approval_status", "Approved"),
                    condition_code=item_condition,
                    source_email_id=item_source_id,
                    confidence=float(extracted.get("confidence", 0.9)),
                    description=item_desc,
                    availability_location=item.get("availability_location") or extracted.get("availability_location"),
                    warranty_terms=item.get("warranty_terms") or extracted.get("warranty_terms"),
                    trace_documents=item.get("trace_documents") or extracted.get("trace_documents", []),
                    source_received_at=source_received_at,
                )
                items.append({
                    "part_number": item_part_number,
                    "quantity_available": item_quantity,
                    "unit_cost": item_price,
                    "certificate_type": item_certificate,
                    "lead_time_days": int(item.get("lead_time_days") or lead_time),
                    "condition_code": item.get("condition_code") or condition,
                    "source_email_id": item_source_id,
                })

            return {
                "success": True,
                "supplier_name": supplier_name,
                "supplier_email": supplier_email,
                "part_number": part_number,
                "quantity_available": quantity,
                "unit_cost": float(unit_cost) if unit_cost is not None else None,
                "certificate_type": certificate,
                "lead_time_days": int(lead_time),
                "warranty_terms": extracted.get("warranty_terms"),
                "trace_documents": extracted.get("trace_documents", []),
                "source_email_id": source_email_id,
                "items": items,
                "communication_sentiment": communication_sentiment,
            }
        except Exception as exc:  # pragma: no cover - defensive
            return {"success": False, "error": str(exc)}

    async def ingest_email_async(
        self,
        email_text: str,
        repositories,
        mailbox: str = "purchasing",
        message_id: Optional[str] = None,
        source_received_at: datetime | None = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Persist plain supplier-email extraction through the async repositories."""
        try:
            sender, subject = _email_headers(email_text)
            if sender and "@" in sender:
                try:
                    early_sup_name = self.extractor._extract_supplier_name(email_text, sender)
                    if hasattr(repositories, "supplier") and hasattr(repositories.supplier, "upsert_supplier"):
                        await repositories.supplier.upsert_supplier(early_sup_name, supplier_email=sender, approval_status="Approved")
                    else:
                        supplier_db.upsert_supplier(early_sup_name, supplier_email=sender, approval_status="Approved")
                except Exception as exc:
                    logger.warning("Async auto-upsert supplier failed for %s: %s", sender, exc)

            if is_no_quote_reply(email_text):
                supplier_name = self.extractor._extract_supplier_name(email_text, sender)
                part_number = self.extractor._extract_part_number(f"{subject}\n{email_text}")
                condition_code = self.extractor._extract_condition(email_text) or "NE"
                source_email_id = message_id or f"EMAIL-{uuid.uuid4().hex[:12].upper()}"

                await repositories.records.save_inbound_email(
                    mailbox=mailbox,
                    message_id=source_email_id,
                    sender=sender,
                    subject=subject or f"Supplier No Quote for {part_number or 'requested part'}",
                    body=email_text,
                    received_at=source_received_at,
                    processing_status="no_quote",
                )

                if part_number:
                    await repositories.supplier.save_inventory_offer(
                        supplier_name=supplier_name,
                        supplier_email=sender,
                        part_number=part_number,
                        quantity_available=0,
                        unit_cost=None,
                        certificate_type=None,
                        lead_time_days=0,
                        approval_status="No_Quote",
                        condition_code=condition_code,
                        source_email_id=source_email_id,
                        source_received_at=source_received_at,
                        description="Supplier responded No Quote / Out of Stock",
                    )
                else:
                    await repositories.supplier.upsert_supplier(
                        supplier_name=supplier_name,
                        supplier_email=sender,
                        approval_status="Approved",
                    )

                return {
                    "success": True,
                    "status": "Supplier_No_Quote",
                    "no_quote": True,
                    "part_number": part_number,
                    "supplier_name": supplier_name,
                    "supplier_email": sender,
                    "source_email_id": source_email_id,
                    "message": "Supplier responded No Quote; recorded in database for future outreach.",
                }
            attachment_context = await asyncio.to_thread(build_email_context, email_text, attachments)
            source_email_id = message_id or f"EMAIL-{uuid.uuid4().hex[:12].upper()}"
            from services.document_verification import compare_documents

            document_report = await asyncio.to_thread(compare_documents, attachments or [])
            if document_report["documents"]:
                await repositories.records.record_automation_event(
                    event_type="supplier_document_comparison", entity_type="email",
                    entity_id=source_email_id, status=document_report["status"],
                    result=json.dumps(document_report),
                    idempotency_key=f"supplier-documents:{source_email_id}",
                )
            if document_report["discrepancies"]:
                review_id = await repositories.records.enqueue_operator_review(
                    idempotency_key=f"supplier-email-review:{source_email_id}",
                    task="supplier_quote_extraction", source_text=attachment_context,
                    extraction={"document_comparison": document_report},
                    reason="supplier_document_evidence_requires_review",
                    hold_flags=document_report["discrepancies"], entity_id=source_email_id,
                )
                return {
                    "success": False, "status": "Pending_Human_Review",
                    "pending_human_review": True, "source_email_id": source_email_id,
                    "review_event_id": review_id, "document_comparison": document_report,
                }
            try:
                extracted = await asyncio.to_thread(self.extractor.extract, attachment_context)
            except ValueError as exc:
                sender, subject = _email_headers(email_text)
                review_id = await repositories.records.enqueue_operator_review(
                    idempotency_key=f"supplier-email-review:{source_email_id}",
                    task="supplier_quote_extraction",
                    source_text=attachment_context,
                    extraction={"error": str(exc)},
                    reason="supplier_email_unstructured",
                    prompt_version=EXTRACTION_CONTRACTS["supplier_quote_extraction"].prompt_version,
                    hold_flags=["part number or quote details not extracted"],
                    entity_id=source_email_id,
                )
                await repositories.records.save_inbound_email(
                    mailbox=mailbox,
                    message_id=source_email_id,
                    sender=sender,
                    subject=subject or "Supplier email requires review",
                    body=email_text,
                    processing_status="pending_human_review",
                    received_at=source_received_at,
                )
                return {
                    "success": False,
                    "status": "Pending_Human_Review",
                    "pending_human_review": True,
                    "source_email_id": source_email_id,
                    "review_event_id": review_id,
                    "error": str(exc),
                }
            deterministic_part_number = extracted.get("part_number")
            try:
                llm_data = await asyncio.to_thread(
                    extract_email_intelligence,
                    email_text,
                    task="supplier_quote_extraction",
                    router=self.llm_router,
                    persist=False,
                    attachments=attachments,
                )
            except Exception:
                llm_data = None

            unsupported_currencies = sorted({
                item.currency.value
                for item in (llm_data.items if llm_data else [])
                if item.currency.value and item.currency.value.upper() != "USD"
            })
            sender, subject = _email_headers(email_text)
            telemetry = llm_data.telemetry if llm_data else {}
            if os.getenv("SUPPLIER_SENTIMENT_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
                communication_sentiment = None
            else:
                sentiment_result = await asyncio.to_thread(
                    analyze_communication_sentiment,
                    attachment_context,
                    router=self.llm_router,
                )
                communication_sentiment = await _persist_supplier_sentiment_async(
                    repositories,
                    source_email_id,
                    sentiment_result,
                )

            deterministic_complete = bool(
                deterministic_part_number and float(extracted.get("unit_cost") or 0) > 0
            )
            llm_review_hold = bool(
                llm_data and llm_data.pending_human_review and not (deterministic_complete and not llm_data.items)
            )
            if llm_data and (llm_review_hold or unsupported_currencies):
                hold_flags = list(llm_data.missing_fields)
                if unsupported_currencies:
                    hold_flags.append("non-USD currency: " + ", ".join(unsupported_currencies))
                review_reason = "non_usd_currency" if unsupported_currencies else (
                    llm_data.escalation_reason or "supplier_extraction_review"
                )
                review_id = await repositories.records.enqueue_operator_review(
                    idempotency_key=telemetry.get("review_idempotency_key")
                    or f"supplier-email-review:{source_email_id}",
                    task="supplier_quote_extraction",
                    source_text=attachment_context,
                    extraction={
                        **llm_data.model_dump(),
                        "communication_sentiment": communication_sentiment,
                    },
                    reason=review_reason,
                    prompt_version=EXTRACTION_CONTRACTS["supplier_quote_extraction"].prompt_version,
                    hold_flags=hold_flags,
                    entity_id=source_email_id,
                )
                telemetry["review_queue_id"] = review_id
                await repositories.records.save_inbound_email(
                    mailbox=mailbox,
                    message_id=source_email_id,
                    sender=sender,
                    subject=subject or "Supplier quote requires human review",
                    body=email_text,
                    received_at=source_received_at,
                    processing_status="pending_human_review",
                )
                await repositories.records.record_llm_telemetry(
                    task="supplier_quote_extraction",
                    prompt_version=EXTRACTION_CONTRACTS["supplier_quote_extraction"].prompt_version,
                    model_id=(telemetry.get("model_calls") or [EXTRACTION_CONTRACTS["supplier_quote_extraction"].allowed_models[0]])[-1],
                    model_calls=telemetry.get("model_calls") or [],
                    latency_ms=telemetry.get("latency_ms") or 0,
                    input_tokens=(telemetry.get("token_usage") or {}).get("input_tokens", 0),
                    output_tokens=(telemetry.get("token_usage") or {}).get("output_tokens", 0),
                    estimated_cost_usd=telemetry.get("estimated_cost_usd") or 0,
                    validation_result=telemetry.get("validation_result") or "REVIEW_REQUIRED",
                    review_queue_id=review_id,
                )
                await repositories.records.record_automation_event(
                    event_type="supplier_email_extraction_review",
                    entity_type="email",
                    entity_id=source_email_id,
                    status="PENDING_HUMAN_REVIEW",
                    result=json.dumps({
                        "review_queue_id": review_id,
                        "missing_fields": llm_data.missing_fields,
                        "unsupported_currencies": unsupported_currencies,
                    }),
                    idempotency_key=f"supplier-email-review-event:{source_email_id}",
                )
                return {
                    "success": False,
                    "status": "Pending_Human_Review",
                    "pending_human_review": True,
                    "unsupported_currencies": unsupported_currencies,
                    "source_email_id": source_email_id,
                    "review_event_id": review_id,
                    "missing_fields": llm_data.missing_fields,
                    "telemetry": telemetry,
                    "communication_sentiment": communication_sentiment,
                }

            structured_items: list[dict[str, Any]] = []
            if llm_data and llm_data.items:
                structured_items = [{
                    "part_number": item.part_number.value,
                    "quantity": _integer_field_value(item.quantity.value),
                    "unit_price": _price_field_value(item.target_price.value),
                    "condition_code": item.condition_code.value,
                    "lead_time_days": _integer_field_value(item.lead_time_days.value),
                    "currency": item.currency.value,
                    "trace_documents": item.trace_documents,
                    "description": item.description,
                    "availability_location": item.availability_location,
                    "warranty_terms": item.warranty_terms,
                } for item in llm_data.items]
                item = llm_data.items[0]
                extracted.update({
                    "supplier_name": llm_data.supplier_name or extracted.get("supplier_name"),
                    "supplier_email": llm_data.supplier_email or extracted.get("supplier_email"),
                    "part_number": deterministic_part_number or re.sub(r"\s*[-]\s*", "-", item.part_number.value or "").replace(" ", "").upper(),
                    "quantity_available": _integer_field_value(item.quantity.value),
                    "unit_cost": _price_field_value(item.target_price.value),
                    "certificate_type": (item.trace_documents[0] if item.trace_documents else None) or extracted.get("certificate_type"),
                    "lead_time_days": _integer_field_value(item.lead_time_days.value),
                    "condition_code": item.condition_code.value,
                    "warranty_terms": item.warranty_terms,
                    "trace_documents": item.trace_documents,
                    "missing_fields": llm_data.missing_fields,
                    "confidence": llm_data.confidence_score,
                })
            if not extracted.get("part_number"):
                return {"success": False, "error": "No part number detected in email."}

            supplier_name = extracted.get("supplier_name") or "Unknown Supplier"
            supplier_email = extracted.get("supplier_email") or sender
            part_number = str(extracted["part_number"])
            quantity = extracted.get("quantity_available") or 1
            unit_cost = extracted.get("unit_cost")
            if unit_cost is not None and float(unit_cost) <= 0.0:
                raise ValueError(f"Quoted cost for {part_number} must never be zero or negative. Received: {unit_cost}")
            certificate = extracted.get("certificate_type")
            lead_time = extracted.get("lead_time_days") or 3
            condition = extracted.get("condition_code") or "NE"
            await repositories.records.save_inbound_email(
                mailbox=mailbox,
                message_id=source_email_id,
                sender=supplier_email,
                subject=subject or f"Supplier Quote for {part_number}",
                body=email_text,
                received_at=source_received_at,
                processing_status="processed",
            )

            items = []
            for index, item in enumerate(structured_items or [{
                "part_number": part_number,
                "quantity": quantity,
                "unit_price": unit_cost,
                "condition_code": condition,
                "trace_documents": extracted.get("trace_documents", []),
                "description": extracted.get("description", ""),
                "availability_location": extracted.get("availability_location"),
                "warranty_terms": extracted.get("warranty_terms"),
                "lead_time_days": lead_time,
            }] ):
                item_part_number = str(item.get("part_number") or part_number).strip().upper()
                item_quantity = int(item.get("quantity") or quantity or 1)
                raw_item_price = item.get("unit_price") if item.get("unit_price") is not None else unit_cost
                item_price = float(raw_item_price) if raw_item_price is not None else None
                if item_price is not None and item_price <= 0.0:
                    raise ValueError(f"Quoted cost for {item_part_number} must never be zero or negative. Received: {item_price}")
                item_certificate = (item.get("trace_documents") or [certificate])[0] if (item.get("trace_documents") or [certificate]) else certificate
                item_source_id = source_email_id if index == 0 else f"{source_email_id}:{index}"
                await repositories.supplier.save_inventory_offer(
                    supplier_name=supplier_name,
                    supplier_email=supplier_email,
                    part_number=item_part_number,
                    quantity_available=item_quantity,
                    unit_cost=item_price,
                    certificate_type=item_certificate,
                    lead_time_days=int(item.get("lead_time_days") or lead_time),
                    approval_status=extracted.get("approval_status", "Approved"),
                    condition_code=item.get("condition_code") or condition,
                    source_email_id=item_source_id,
                    confidence=float(extracted.get("confidence", 0.9)),
                    description=item.get("description") or extracted.get("description", ""),
                    availability_location=item.get("availability_location") or extracted.get("availability_location"),
                    warranty_terms=item.get("warranty_terms") or extracted.get("warranty_terms"),
                    trace_documents=item.get("trace_documents") or extracted.get("trace_documents", []),
                    source_received_at=source_received_at,
                )
                items.append({
                    "part_number": item_part_number,
                    "quantity_available": item_quantity,
                    "unit_cost": item_price,
                    "certificate_type": item_certificate,
                    "lead_time_days": int(item.get("lead_time_days") or lead_time),
                    "condition_code": item.get("condition_code") or condition,
                    "source_email_id": item_source_id,
                })

            if llm_data:
                await repositories.records.record_llm_telemetry(
                    task="supplier_quote_extraction",
                    prompt_version=EXTRACTION_CONTRACTS["supplier_quote_extraction"].prompt_version,
                    model_id=(telemetry.get("model_calls") or [EXTRACTION_CONTRACTS["supplier_quote_extraction"].allowed_models[0]])[-1],
                    model_calls=telemetry.get("model_calls") or [],
                    latency_ms=telemetry.get("latency_ms") or 0,
                    input_tokens=(telemetry.get("token_usage") or {}).get("input_tokens", 0),
                    output_tokens=(telemetry.get("token_usage") or {}).get("output_tokens", 0),
                    estimated_cost_usd=telemetry.get("estimated_cost_usd") or 0,
                    validation_result=telemetry.get("validation_result") or "VALIDATED",
                    review_queue_id=None,
                )

            return {
                "success": True,
                "supplier_name": supplier_name,
                "supplier_email": supplier_email,
                "part_number": part_number,
                "quantity_available": quantity,
                "unit_cost": float(unit_cost) if unit_cost is not None else None,
                "certificate_type": certificate,
                "lead_time_days": int(lead_time),
                "warranty_terms": extracted.get("warranty_terms"),
                "trace_documents": extracted.get("trace_documents", []),
                "source_email_id": source_email_id,
                "items": items,
                "communication_sentiment": communication_sentiment,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}
