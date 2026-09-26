import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.supplier_database import supplier_db
from services.supplier_email_extractor import SupplierEmailExtractor
from services.email_intelligence import extract_email_intelligence
from services.document_parser import build_email_context
from services.llm_provider import LLMRouter
from services.operations_store import operations_store


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
            if llm_data and llm_data.pending_human_review:
                sender = ""
                subject = ""
                for line in email_text.splitlines():
                    if line.lower().startswith("from:"):
                        sender = line.split(":", 1)[1].strip()
                    elif line.lower().startswith("subject:"):
                        subject = line.split(":", 1)[1].strip()
                source_email_id = message_id or f"EMAIL-{uuid.uuid4().hex[:12].upper()}"
                supplier_db.save_email(
                    mailbox=mailbox,
                    message_id=source_email_id,
                    sender=sender,
                    subject=subject or "Supplier quote requires human review",
                    body=email_text,
                )
                review_event_id = operations_store.record_automation_event(
                    event_type="supplier_email_extraction_review",
                    entity_type="email",
                    entity_id=source_email_id,
                    status="PENDING_HUMAN_REVIEW",
                    result=json.dumps({
                        "pending_human_review": True,
                        "missing_fields": llm_data.missing_fields,
                        "telemetry": llm_data.telemetry,
                    }),
                    idempotency_key=f"supplier-email-review:{source_email_id}",
                )
                return {
                    "success": False,
                    "status": "Pending_Human_Review",
                    "pending_human_review": True,
                    "source_email_id": source_email_id,
                    "review_event_id": review_event_id,
                    "missing_fields": llm_data.missing_fields,
                    "telemetry": llm_data.telemetry,
                }
            if llm_data and llm_data.items:
                structured_items = [item.model_dump() for item in llm_data.items]
                item = llm_data.items[0]
                extracted.update({
                    "supplier_name": llm_data.supplier_name or extracted.get("supplier_name"),
                    "supplier_email": llm_data.supplier_email or extracted.get("supplier_email"),
                    "part_number": (
                        deterministic_part_number
                        or re.sub(r"\s*[-]\s*", "-", item.part_number).replace(" ", "").upper()
                    ),
                    "quantity_available": item.quantity,
                    "unit_cost": item.unit_price,
                    "certificate_type": (item.trace_documents[0] if item.trace_documents else None) or extracted.get("certificate_type"),
                    "lead_time_days": item.lead_time_days,
                    "condition_code": item.condition_code,
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
            source_email_id = message_id or f"EMAIL-{uuid.uuid4().hex[:12].upper()}"

            supplier_db.save_email(
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
                supplier_db.save_supplier_offer(
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
                "part_number": part_number,
                "quantity_available": quantity,
                "unit_cost": float(unit_cost),
                "certificate_type": certificate,
                "lead_time_days": int(lead_time),
                "warranty_terms": extracted.get("warranty_terms"),
                "trace_documents": extracted.get("trace_documents", []),
                "source_email_id": source_email_id,
                "items": items,
            }
        except Exception as exc:  # pragma: no cover - defensive
            return {"success": False, "error": str(exc)}
