import asyncio
import json
import logging
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


def _save_inbound_email(*, mailbox: str, message_id: str, sender: str, subject: str, body: str) -> None:
    if operations_store.storage_engine == "postgresql":
        operations_store.save_inbound_email(
            mailbox=mailbox, message_id=message_id, sender=sender,
            subject=subject, body=body, processing_status="processed",
        )
        return
    supplier_db.save_email(mailbox=mailbox, message_id=message_id, sender=sender, subject=subject, body=body)


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

    def ingest_email(self, email_text: str, mailbox: str = "purchasing", message_id: Optional[str] = None, attachments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        try:
            attachment_context = build_email_context(email_text, attachments)
            extracted = self.extractor.extract(attachment_context)
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
            source_email_id = message_id or f"EMAIL-{uuid.uuid4().hex[:12].upper()}"
            sentiment_result = analyze_communication_sentiment(
                attachment_context,
                router=self.llm_router,
            )
            communication_sentiment = _persist_supplier_sentiment(
                source_email_id,
                sentiment_result,
            )
            unsupported_currencies = sorted({
                item.currency.value
                for item in (llm_data.items if llm_data else [])
                if item.currency.value and item.currency.value.upper() != "USD"
            })
            if llm_data and (llm_data.pending_human_review or unsupported_currencies):
                sender = ""
                subject = ""
                for line in email_text.splitlines():
                    if line.lower().startswith("from:"):
                        sender = line.split(":", 1)[1].strip()
                    elif line.lower().startswith("subject:"):
                        subject = line.split(":", 1)[1].strip()
                _save_inbound_email(
                    mailbox=mailbox,
                    message_id=source_email_id,
                    sender=sender,
                    subject=subject or "Supplier quote requires human review",
                    body=email_text,
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
            unit_cost = extracted.get("unit_cost") or 0.0
            certificate = extracted.get("certificate_type")
            lead_time = extracted.get("lead_time_days") or 3
            condition = extracted.get("condition_code") or "NE"
            _save_inbound_email(
                mailbox=mailbox,
                message_id=source_email_id,
                sender=supplier_email,
                subject=subject or f"Supplier Quote for {part_number}",
                body=email_text,
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
                item_part_number = str(item.get("part_number") or part_number).strip().upper()
                item_quantity = int(item.get("quantity") or quantity or 1)
                item_price = float(item.get("unit_price") if item.get("unit_price") is not None else unit_cost or 0.0)
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
                    condition_code=item.get("condition_code") or condition,
                    source_email_id=item_source_id,
                    confidence=float(extracted.get("confidence", 0.9)),
                    description=item.get("description") or extracted.get("description", ""),
                    availability_location=item.get("availability_location") or extracted.get("availability_location"),
                    warranty_terms=item.get("warranty_terms") or extracted.get("warranty_terms"),
                    trace_documents=item.get("trace_documents") or extracted.get("trace_documents", []),
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
                "unit_cost": float(unit_cost),
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
    ) -> Dict[str, Any]:
        """Persist plain supplier-email extraction through the async repositories."""
        try:
            attachment_context = build_email_context(email_text, None)
            extracted = await asyncio.to_thread(self.extractor.extract, attachment_context)
            deterministic_part_number = extracted.get("part_number")
            try:
                llm_data = await asyncio.to_thread(
                    extract_email_intelligence,
                    email_text,
                    task="supplier_quote_extraction",
                    router=self.llm_router,
                    persist=False,
                )
            except Exception:
                llm_data = None

            unsupported_currencies = sorted({
                item.currency.value
                for item in (llm_data.items if llm_data else [])
                if item.currency.value and item.currency.value.upper() != "USD"
            })
            sender = ""
            subject = ""
            for line in email_text.splitlines():
                if line.lower().startswith("from:"):
                    sender = line.split(":", 1)[1].strip()
                elif line.lower().startswith("subject:"):
                    subject = line.split(":", 1)[1].strip()
            source_email_id = message_id or f"EMAIL-{uuid.uuid4().hex[:12].upper()}"
            telemetry = llm_data.telemetry if llm_data else {}
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

            if llm_data and (llm_data.pending_human_review or unsupported_currencies):
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
            unit_cost = extracted.get("unit_cost") or 0.0
            certificate = extracted.get("certificate_type")
            lead_time = extracted.get("lead_time_days") or 3
            condition = extracted.get("condition_code") or "NE"
            await repositories.records.save_inbound_email(
                mailbox=mailbox,
                message_id=source_email_id,
                sender=supplier_email,
                subject=subject or f"Supplier Quote for {part_number}",
                body=email_text,
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
                item_price = float(item.get("unit_price") if item.get("unit_price") is not None else unit_cost or 0.0)
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
                "unit_cost": float(unit_cost),
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
