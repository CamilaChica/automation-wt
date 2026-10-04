import json
import logging
import math
import re
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from services.db_service import db_service
from agents.base_agent import AgentResponse
from agents.rfq_intake_agent import RFQIntakeAgent
from agents.parts_intelligence_agent import PartsIntelligenceAgent
from agents.inventory_agent import InventoryAgent
from agents.supplier_discovery_agent import SupplierDiscoveryAgent
from agents.compliance_agent import ComplianceAgent
from agents.pricing_agent import PricingAgent
from agents.quote_generation_agent import QuoteGenerationAgent
from agents.customer_communication_agent import CustomerCommunicationAgent
from services.communication_service import communication_service
from services.storage import storage_service
from services.agents.prompts import AgentPipelineState
from services.operations_store import operations_store
from services.supplier_database import supplier_db
from services.email_program_runtime import email_program_runtime

logger = logging.getLogger(__name__)


class ReviewDecisionConflict(RuntimeError):
    """Raised when a review is no longer pending or a decision is already claimed."""


class ReviewDecisionValidationError(ValueError):
    """Raised when an operator decision includes unsupported extraction values."""


def _lead_time_days(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None


def _review_price(value: Any) -> Optional[float]:
    normalized = re.sub(r"[^0-9.]", "", str(value or ""))
    try:
        price = float(normalized)
    except ValueError:
        return None
    return price if price > 0 else None


def _is_partsbase_rfq(rfq: Any) -> bool:
    source = f"{getattr(rfq, 'customer_email', '')} {getattr(rfq, 'raw_text', '')}".lower()
    return "partsbase.com" in source

class OrchestrationService:
    MIN_AUTONOMOUS_MARGIN = 0.18

    def __init__(self):
        self.storage = storage_service
        self.intake_agent = RFQIntakeAgent()
        self.parts_intel_agent = PartsIntelligenceAgent()
        self.inventory_agent = InventoryAgent()
        self.supplier_agent = SupplierDiscoveryAgent()
        self.compliance_agent = ComplianceAgent()
        self.pricing_agent = PricingAgent()
        self.quote_agent = QuoteGenerationAgent()
        self.comm_agent = CustomerCommunicationAgent()
        self._pipeline_state_cache: Dict[str, Dict[str, Any]] = {}

    def _load_pipeline_state(self, rfq_id: str) -> Dict[str, Any]:
        if operations_store.storage_engine == "postgresql":
            return operations_store.get_operational_record(
                "rfq_pipeline_state", rfq_id
            ) or {}
        return dict(self._pipeline_state_cache.get(rfq_id, {}))

    def _save_pipeline_state(self, rfq_id: str, **updates: Any) -> Dict[str, Any]:
        state = self._load_pipeline_state(rfq_id)
        state.update(updates)
        if operations_store.storage_engine == "postgresql":
            with operations_store.transaction():
                operations_store.save_operational_record(
                    "rfq_pipeline_state", rfq_id, state
                )
        else:
            self._pipeline_state_cache[rfq_id] = state
        return state

    @staticmethod
    def _requested_certification(raw_text: str) -> Optional[str]:
        text = (raw_text or "").lower()
        if "easa form 1" in text:
            return "EASA Form 1"
        if "coc" in text or "certificate of conformity" in text:
            return "CoC"
        if "8130" in text:
            return "FAA 8130-3"
        return None

    async def _request_partsbase_quote(self, rfq_id: str, part_number: str, quantity: int) -> Dict[str, Any]:
        from services import partsbase_service

        part = str(part_number or "").strip().upper()
        if not part or quantity < 1:
            raise ValueError("PartsBase sourcing requires a part number and positive requested quantity.")
        request_key = f"{part}:{quantity}"
        state = self._load_pipeline_state(rfq_id)
        submissions = dict(state.get("partsbase_submissions") or {})
        previous = submissions.get(request_key)
        if previous:
            return {**previous, "reused": True}

        if not partsbase_service.credentials_configured():
            result = {
                "part_number": part,
                "quantity": quantity,
                "status": "not_configured",
                "error": "PartsBase credentials are not configured.",
            }
            db_service.add_audit_log(
                rfq_id, "PartsBase", "rfq_submission",
                "Automatic PartsBase RFQ was not sent because server credentials are not configured.",
                "WARNING", json.dumps(result),
            )
            operations_store.enqueue_operator_review(
                idempotency_key=f"partsbase-config:{rfq_id}:{request_key}",
                task="partsbase_configuration",
                source_text=part,
                extraction={"rfq_id": rfq_id, "part_number": part, "quantity": quantity},
                reason=result["error"],
                entity_id=rfq_id,
            )
            return result

        submissions[request_key] = {
            "part_number": part,
            "quantity": quantity,
            "status": "submitting",
        }
        self._save_pipeline_state(rfq_id, partsbase_submissions=submissions)
        try:
            response = await partsbase_service.request_partsbase_quote(
                [part], quantities={part: quantity}
            )
            if response.get("status") != "sent":
                raise RuntimeError("PartsBase did not confirm RFQ submission.")
        except partsbase_service.PartsBaseNoResults:
            result = {"part_number": part, "quantity": quantity, "status": "not_found"}
            status = "WARNING"
        except Exception as exc:
            result = {
                "part_number": part,
                "quantity": quantity,
                "status": "submission_unknown",
                "error": f"{type(exc).__name__}: {exc}",
            }
            logger.exception("PartsBase RFQ submission failed rfq=%s part=%s", rfq_id, part)
            operations_store.enqueue_operator_review(
                idempotency_key=f"partsbase-submit:{rfq_id}:{request_key}",
                task="partsbase_rfq_submission",
                source_text=part,
                extraction={"rfq_id": rfq_id, "part_number": part, "quantity": quantity},
                reason=result["error"],
                entity_id=rfq_id,
            )
            status = "FAILURE"
        else:
            result = {
                "part_number": part,
                "quantity": quantity,
                "status": "sent",
                "response": response,
            }
            status = "PENDING"
        submissions[request_key] = result
        self._save_pipeline_state(rfq_id, partsbase_submissions=submissions)
        db_service.add_audit_log(
            rfq_id, "PartsBase", "rfq_submission",
            (
                f"PartsBase RFQ submitted for {part}, quantity {quantity}; awaiting a supplier response."
                if status == "PENDING"
                else f"No matching PartsBase listing found for {part}; customer verification is required."
                if result["status"] == "not_found"
                else f"PartsBase submission outcome is unknown for {part}, quantity {quantity}; operator review is required."
            ),
            status, json.dumps(result),
        )
        return result

    def _halt_retrieval_fault(self, rfq_id: str, part_number: str, stage: str, error: Exception) -> Dict[str, Any]:
        logger.error("critical_catalog_retrieval_fault rfq=%s part=%s stage=%s",
                     rfq_id, part_number, stage, exc_info=error)
        db_service.update_rfq_status(rfq_id, "Verification_Halted")
        db_service.set_rfq_automation_paused(rfq_id, True, f"Critical {stage} retrieval failure")
        operations_store.enqueue_operator_review(
            idempotency_key=f"catalog-system-error:{rfq_id}:{stage}:{part_number}",
            task="catalog_infrastructure_fault",
            source_text=part_number,
            extraction={"rfq_id": rfq_id, "part_number": part_number, "stage": stage,
                        "diagnosis": "system_error", "severity": "CRITICAL", "error_type": type(error).__name__},
            reason=f"Critical {stage} retrieval failure; automated customer responses halted.",
            hold_flags=["critical_infrastructure_fault"],
            entity_id=rfq_id,
        )
        return {"status": "Verification_Halted", "diagnosis": "system_error",
                "error": f"{stage} retrieval failed; engineering review required."}

    def _request_pn_verification(self, rfq: Any, part_number: str) -> Dict[str, Any]:
        state = self._load_pipeline_state(rfq.id)
        pending = list(state.get("pn_confirmation_required") or [])
        if part_number not in pending:
            pending.append(part_number)
        self._save_pipeline_state(rfq.id, pn_confirmation_required=pending)
        communication_service.send_rfq_update_reply(
            recipient=rfq.customer_email, customer_name=rfq.customer_name,
            rfq_id=rfq.id, customer_text="", original_subject=f"Request for quote {rfq.id}",
            reply_to=rfq.thread_id, inbound_message_id=f"pn-verification:{part_number}",
            quote_answer=(
                f"We could not find a matching PartsBase listing for P/N {part_number}. "
                "Please double-check the full part number, including its suffix, and confirm it in your reply. "
                "If you confirm it is correct and we have no verified offer, we will close this item as No Quote."
            ),
        )
        return {"status": "Supplier_Sourcing", "diagnosis": "pn_verification_required",
                "part_number": part_number}

    @classmethod
    def _historical_reference_price(cls, offers: List[Dict[str, Any]], quantity: int) -> float | None:
        eligible = [
            offer for offer in offers
            if str(offer.get("currency") or "").upper() == "USD"
            and offer.get("approval_status") == "Approved"
            and offer.get("certificate_type") in SupplierDiscoveryAgent.REQUIRED_TRACE_CERTIFICATES
            and float(offer.get("unit_cost") or 0) > 0
            and math.isfinite(float(offer["unit_cost"]))
        ]
        if not eligible:
            return None
        latest = max(eligible, key=lambda offer: str(offer.get("source_received_at") or ""))
        pricing, low_margin = cls.calculate_pricing(float(latest["unit_cost"]), quantity)
        return None if low_margin else pricing["suggested_unit_price"]

    @classmethod
    def calculate_pricing(
        cls,
        unit_cost: float,
        quantity: int,
        requested_price_limit: float | None = None,
    ) -> tuple[Dict[str, float], bool]:
        """Apply the deterministic margin matrix used by every quote path."""
        margin = 0.20
        if quantity >= 10:
            margin = 0.15
        elif quantity >= 5:
            margin = 0.18
        if requested_price_limit and requested_price_limit > 0:
            suggested_unit_price = float(requested_price_limit)
            actual_margin = (suggested_unit_price - unit_cost) / suggested_unit_price
        else:
            actual_margin = margin
            suggested_unit_price = round(unit_cost / (1 - actual_margin), 2)
        if suggested_unit_price <= unit_cost:
            raise ValueError(
                f"Customer price ${suggested_unit_price:.2f} must exceed source cost ${unit_cost:.2f}."
            )
        return ({
            "unit_cost": float(unit_cost),
            "suggested_unit_price": suggested_unit_price,
            "margin_percent": round(actual_margin * 100, 2),
            "calculated_markup_amount": round(suggested_unit_price - unit_cost, 2),
        }, actual_margin < cls.MIN_AUTONOMOUS_MARGIN)

    def set_automation_pause(self, rfq_id: str, paused: bool, reason: Optional[str], operator: str) -> Dict[str, Any]:
        rfq = db_service.set_rfq_automation_paused(rfq_id, paused, reason)
        if not rfq:
            raise ValueError(f"RFQ {rfq_id} not found.")
        db_service.add_audit_log(
            rfq_id,
            "AutomationControl",
            "automation_pause" if paused else "automation_resume",
            f"Automation {'paused' if paused else 'resumed'} by {operator}."
            + (f" Reason: {rfq.pause_reason}" if rfq.pause_reason else ""),
            "WARNING" if paused else "SUCCESS",
        )
        return {"rfq_id": rfq_id, "automation_paused": rfq.automation_paused, "pause_reason": rfq.pause_reason}

    def record_trace_decision(self, rfq_id: str, decision: str, reason: str, operator: str) -> Dict[str, Any]:
        rfq = db_service.get_rfq(rfq_id)
        if not rfq:
            raise ValueError(f"RFQ {rfq_id} not found.")
        if decision == "freeze":
            db_service.set_rfq_automation_paused(rfq_id, True, reason)
        db_service.add_audit_log(
            rfq_id,
            "TraceVault",
            f"trace_{decision}",
            reason or f"Trace decision '{decision}' recorded by {operator}.",
            "WARNING" if decision in {"reject", "freeze"} else "SUCCESS",
        )
        updated = db_service.get_rfq(rfq_id)
        return {"rfq_id": rfq_id, "decision": decision, "automation_paused": updated.automation_paused if updated else decision == "freeze"}

    def apply_signed_carrier_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Apply an authenticated carrier event idempotently inside backend orchestration."""
        shipment = db_service.find_shipment_by_tracking(
            event.get("carrier", ""), event.get("tracking_number", "")
        )
        if not shipment:
            raise ValueError("No shipment matches carrier tracking event.")
        if not operations_store.claim_carrier_webhook_event(event["event_id"]):
            return {"status": "duplicate", "shipment_id": shipment.id}
        saved_event = db_service.add_shipment_event(
            shipment.id,
            event["status"],
            event.get("location"),
            event["description"],
        )
        return {"status": "accepted", "shipment_id": shipment.id, "event_id": saved_event.id}

    def block_rfq_for_compliance(self, rfq_id: str, screening: Any) -> None:
        db_service.update_rfq_status(rfq_id, "Blocked_Compliance_Review")
        db_service.add_audit_log(
            rfq_id,
            "ExportControlService",
            "export_screening",
            "RFQ blocked pending export-control compliance review.",
            "FAILURE",
            json.dumps(screening.model_dump() if hasattr(screening, "model_dump") else screening),
        )

    def reject_quote(self, quote_id: str, operator_name: str, comments: str) -> Dict[str, Any]:
        quote = db_service.get_quote(quote_id)
        if not quote:
            return {"error": f"Quote {quote_id} not found."}
        db_service.update_quote_status(quote_id, "Rejected", approved_by=operator_name, comments=comments)
        db_service.update_rfq_status(quote.rfq_id, "Rejected")
        db_service.add_audit_log(
            quote.rfq_id,
            "Orchestrator",
            "human_rejection",
            f"Quote rejected by {operator_name}. Reason: {comments}",
            "WARNING",
        )
        return {"status": "Rejected", "quote_id": quote_id}

    def mark_purchase_order_received(self, rfq_id: str, po_number: str, attachment_ids: List[str]) -> None:
        rfq = db_service.get_rfq(rfq_id)
        if not rfq:
            raise ValueError(f"RFQ {rfq_id} not found.")
        if rfq.status in {"Purchase_Order_Received", "Pending_PO_Review"}:
            raise ValueError("Purchase order already received for this RFQ.")
        db_service.update_rfq_status(rfq_id, "Pending_PO_Review")
        db_service.add_audit_log(
            rfq_id,
            "PurchaseOrderAgent",
            "purchase_order_received",
            f"Purchase order {po_number} received; fulfillment and invoicing are blocked pending human review.",
            "SUCCESS",
            json.dumps({"attachment_ids": attachment_ids}),
        )

    def approve_purchase_order(self, rfq_id: str, operator_name: str, comments: str | None = None) -> None:
        rfq = db_service.get_rfq(rfq_id)
        if not rfq:
            raise ValueError(f"RFQ {rfq_id} not found.")
        if rfq.status != "Pending_PO_Review":
            raise ValueError("PO is not waiting for human review.")
        db_service.update_rfq_status(rfq_id, "Purchase_Order_Received")
        db_service.add_audit_log(
            rfq_id,
            "PurchaseOrderAgent",
            "purchase_order_approved",
            f"PO approved by {operator_name}; downstream purchasing may proceed."
            + (f" Comments: {comments}" if comments else ""),
            "SUCCESS",
        )

    async def decide_extraction_review(
        self,
        *,
        review: Dict[str, Any],
        decision: str,
        operator: str,
        comments: Optional[str] = None,
        approved_extraction: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Apply an operator decision and downstream state changes without LLM calls."""
        from services.email_intelligence import (
            EmailIntelligenceExtraction,
            _validate_source_grounding,
            is_valid_extracted_part_number,
        )

        review_id = str(review["id"])
        decision = decision.upper()
        if decision not in {"APPROVE", "REJECT"}:
            raise ReviewDecisionValidationError("Decision must be APPROVE or REJECT.")
        if review.get("status") != "PENDING":
            raise ReviewDecisionConflict(f"Review is already {str(review.get('status')).lower()}.")

        if decision == "REJECT":
            if not operations_store.claim_operator_review_decision(
                review_id, decision, operator, {"comments": comments}
            ):
                raise ReviewDecisionConflict("Review was already claimed by another operator.")
            if review.get("task") == "rfq_extraction" and review.get("entity_id"):
                rfq = db_service.get_rfq(review["entity_id"])
                if rfq and rfq.status == "Pending_Internal_Review":
                    db_service.update_rfq_status(rfq.id, "Rejected")
                    db_service.add_audit_log(
                        rfq.id,
                        "ExtractionReview",
                        "rejected",
                        f"Extraction rejected by {operator}. {comments or ''}",
                        "WARNING",
                    )
            operations_store.complete_operator_review_decision(review_id, status="REJECTED")
            return {"review_id": review_id, "status": "REJECTED", "decision_by": operator}

        try:
            extraction = EmailIntelligenceExtraction.model_validate(
                approved_extraction or review["extraction"]
            )
        except Exception as exc:
            raise ReviewDecisionValidationError(
                f"Approved extraction does not match the schema: {exc}"
            ) from exc

        missing = _validate_source_grounding(extraction, review["source_text"], review["task"])
        if missing:
            raise ReviewDecisionValidationError(
                "Approval requires source-grounded required fields: " + ", ".join(missing)
            )
        if not extraction.items:
            raise ReviewDecisionValidationError("Approval requires at least one source-grounded item.")
        if any(not is_valid_extracted_part_number(item.part_number.value or "") for item in extraction.items):
            raise ReviewDecisionValidationError("Approval includes an invalid or reference-like part number.")

        if review["task"] == "supplier_quote_extraction":
            non_usd = [
                item.currency.value
                for item in extraction.items
                if item.currency.value and item.currency.value.upper() != "USD"
            ]
            if non_usd:
                raise ReviewDecisionConflict(
                    "Non-USD supplier quotes remain held until a separately verified USD conversion is provided."
                )
            if any(not item.trace_documents for item in extraction.items):
                raise ReviewDecisionValidationError(
                    "Supplier offer approval requires source-grounded release certificate evidence."
                )
        elif review["task"] != "rfq_extraction":
            raise ReviewDecisionConflict("This extraction task has no downstream approval handler.")

        if not operations_store.claim_operator_review_decision(
            review_id,
            decision,
            operator,
            {"comments": comments, "approved_extraction": extraction.model_dump()},
        ):
            raise ReviewDecisionConflict("Review was already claimed by another operator.")

        try:
            if review["task"] == "rfq_extraction":
                rfq = db_service.get_rfq(str(review.get("entity_id") or ""))
                if not rfq or rfq.status != "Pending_Internal_Review":
                    raise ReviewDecisionConflict("The linked RFQ is not waiting for extraction review.")
                db_service.update_rfq_customer(
                    rfq.id,
                    extraction.customer_company or extraction.customer_name or rfq.customer_name,
                    extraction.customer_email or rfq.customer_email,
                )
                db_service.replace_rfq_items(rfq.id, [{
                    "part_number": item.part_number.value,
                    "quantity": int(item.quantity.value or "0"),
                    "condition_code": item.condition_code.value,
                    "unit_of_measure": item.unit_of_measure.value,
                    "description": getattr(item, "description", None) or None,
                    "target_price": _review_price(item.target_price.value),
                    "currency": (item.currency.value or "").strip().upper() or None,
                } for item in extraction.items])
                db_service.update_rfq_status(rfq.id, "Validating")
                db_service.add_audit_log(
                    rfq.id,
                    "ExtractionReview",
                    "approved",
                    f"Source-grounded extraction approved by {operator}. {comments or ''}",
                    "SUCCESS",
                    json.dumps(extraction.model_dump()),
                )
                operations_store.complete_operator_review_decision(review_id, status="APPROVED")
                pipeline_result = await self.process_rfq_pipeline(rfq.id)
                return {
                    "review_id": review_id,
                    "status": "APPROVED",
                    "rfq_id": rfq.id,
                    "pipeline": pipeline_result,
                }

            sender = ""
            for line in review["source_text"].splitlines():
                if line.lower().startswith("from:"):
                    sender = line.split(":", 1)[1].strip()
                    break
            source_id = review.get("entity_id") or review_id
            approved_offers = []
            for index, item in enumerate(extraction.items):
                price = float(re.sub(r"[^0-9.\-]", "", item.target_price.value or ""))
                quantity = int(re.search(r"\d+", item.quantity.value or "").group())
                lead_time_match = re.search(r"\d+", item.lead_time_days.value or "")
                offer = {
                    "supplier_name": extraction.supplier_name or "Supplier Pending Identification",
                    "supplier_email": extraction.supplier_email or sender,
                    "part_number": item.part_number.value or "",
                    "quantity_available": quantity,
                    "unit_cost": price,
                    "certificate_type": item.trace_documents[0],
                    "lead_time_days": int(lead_time_match.group()) if lead_time_match else None,
                    "approval_status": "Pending",
                    "condition_code": item.condition_code.value,
                    "source_email_id": f"{source_id}:{index}" if index else str(source_id),
                    "confidence": extraction.confidence_score,
                    "trace_documents": item.trace_documents,
                }
                approved_offers.append(
                    operations_store.save_supplier_offer(**offer)
                    if operations_store.storage_engine == "postgresql"
                    else supplier_db.save_supplier_offer(**offer)
                )
            operations_store.complete_operator_review_decision(review_id, status="APPROVED")
            return {"review_id": review_id, "status": "APPROVED", "offers": approved_offers}
        except Exception as exc:
            operations_store.complete_operator_review_decision(
                review_id,
                status="PENDING",
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

    async def process_rfq_pipeline(self, rfq_id: str) -> Dict[str, Any]:
        """
        Executes the RFQ automated pipeline.
        Steps: Intake -> Validate -> Inventory -> Supplier Sourcing -> Compliance -> Pricing -> Quote Gen.
        Halts on any validation issues, compliance blocks, or pricing anomalies.
        """
        pipeline_state = self._load_pipeline_state(rfq_id)
        allocated_sources = dict(pipeline_state.get("allocated_sources") or {})
        rfq = db_service.get_rfq(rfq_id)
        if not rfq:
            return {"error": f"RFQ {rfq_id} not found."}
        if rfq.automation_paused:
            return {
                "status": "Automation_Paused",
                "rfq_id": rfq_id,
                "reason": rfq.pause_reason or "Paused by an operator.",
            }
        if rfq.status in {"Supplier_Confirmation_Requested", "Sourcing_Failed"}:
            db_service.update_rfq_status(rfq_id, "Supplier_Sourcing")
            rfq = db_service.get_rfq(rfq_id)

        # 1. RFQ Intake Check
        if rfq.status == "Intake":
            db_service.add_audit_log(rfq_id, "Orchestrator", "transition", "Starting RFQ Intake processing stage.")
            res = await self.intake_agent.execute({
                "rfq_id": rfq_id,
                "raw_text": rfq.raw_text,
                "customer_name": rfq.customer_name,
                "customer_email": rfq.customer_email,
                "communication_sentiment": pipeline_state.get("communication_sentiment"),
            })
            if isinstance(res.data, dict) and res.data.get("communication_sentiment"):
                pipeline_state = self._save_pipeline_state(
                    rfq_id,
                    communication_sentiment=res.data["communication_sentiment"],
                )
            
            if not res.success:
                intake_data = res.data or {}
                requires_internal_review = (
                    intake_data.get("pending_human_review") is True
                    or
                    intake_data.get("AOG_status") is True
                    or intake_data.get("priority") in {"AOG", "Urgent"}
                )
                if requires_internal_review:
                    db_service.update_rfq_customer(
                        rfq_id,
                        intake_data.get("company") or intake_data.get("customer_name"),
                        intake_data.get("customer_email"),
                    )
                    for item in intake_data.get("items", []):
                        requested_part = item.get("requested_part_number")
                        requested_quantity = item.get("quantity")
                        if requested_part and isinstance(requested_quantity, int) and requested_quantity > 0:
                            db_service.add_rfq_item(
                                rfq_id=rfq_id,
                                requested_part=requested_part,
                                qty=requested_quantity,
                                uom=item.get("uom", "EA"),
                                aircraft=item.get("aircraft_type"),
                                condition=item.get("condition_preference", "NE"),
                                description=item.get("description"),
                                target_price=item.get("target_price"),
                                currency=item.get("currency"),
                            )
                    db_service.update_rfq_status(rfq_id, "Pending_Internal_Review")
                    db_service.add_audit_log(
                        rfq_id,
                        "RFQIntakeAgent",
                        "intake_review",
                        f"RFQ requires internal review: {res.error_message}",
                        "WARNING",
                        json.dumps(intake_data),
                    )
                    return {
                        "status": "Pending_Internal_Review",
                        "message": "AOG/urgent RFQ parsed and queued for internal review.",
                        "review_required": True,
                    }
                db_service.update_rfq_status(rfq_id, "Intake_Failed")
                db_service.add_audit_log(
                    rfq_id, "RFQIntakeAgent", "intake_parse", 
                    f"Intake failed: {res.error_message}", "FAILURE", 
                    json.dumps(res.dict())
                )
                return {"status": "Intake_Failed", "error": res.error_message, "escalation": res.escalation_triggered}
                
            # Populate DB with extracted items
            items_data = res.data.get("items", [])
            existing_rfq = db_service.get_rfq(rfq_id)
            # Portal-provided identity is authoritative; parsed values only fill gaps.
            db_service.update_rfq_customer(
                rfq_id,
                (lambda n: n if n and "@" not in n else "")((getattr(existing_rfq, "customer_name", None) or "").strip())
                or res.data.get("company") or res.data.get("customer_name"),
                (getattr(existing_rfq, "customer_email", None) or "").strip()
                or res.data.get("customer_email"),
            )
            for item in items_data:
                db_service.add_rfq_item(
                    rfq_id=rfq_id,
                    requested_part=item["requested_part_number"],
                    qty=item["quantity"],
                    uom=item.get("uom", "EA"),
                    aircraft=item.get("aircraft_type"),
                    condition=item.get("condition_preference", "NE"),
                    description=item.get("description"),
                    target_price=item.get("target_price"),
                    currency=item.get("currency"),
                )
            
            # Log success and update status
            db_service.add_audit_log(
                rfq_id, "RFQIntakeAgent", "intake_parse",
                f"Successfully parsed customer request from {res.data.get('customer_name')}. Extracted {len(items_data)} items.",
                "SUCCESS", json.dumps(res.data)
            )
            rfq = db_service.update_rfq_status(rfq_id, "Validating")
            try:
                communication_service.send_rfq_acknowledgement(
                    rfq_id=rfq_id,
                    recipient=rfq.customer_email,
                    customer_name=rfq.customer_name,
                    part_numbers=[item.get("requested_part_number") for item in items_data],
                    reply_to=rfq.thread_id,
                    items=items_data,
                    certifications=res.data.get("certification_requirements") or [],
                )
            except Exception as exc:
                logger.warning("rfq_acknowledgement_failed rfq_id=%s error=%s", rfq_id, type(exc).__name__)

        # 2. Part Catalog Validation Stage
        if rfq.status == "Validating":
            db_service.add_audit_log(rfq_id, "Orchestrator", "transition", "Starting part number catalog validation.")
            items = db_service.get_rfq_items(rfq_id)
            
            for item in items:
                try:
                    res = await self.parts_intel_agent.execute({"requested_part_number": item.requested_part_number})
                except Exception as exc:
                    return self._halt_retrieval_fault(rfq_id, item.requested_part_number, "catalog", exc)
                
                if not res.success:
                    unknown_part = (
                        res.escalation_triggered is not None
                        and res.escalation_triggered.condition == "part_not_found"
                    ) or res.data.get("match_type") == "none"
                    if unknown_part:
                        transaction = operations_store.transaction() if operations_store.storage_engine == "postgresql" else nullcontext()
                        with transaction:
                            db_service.update_rfq_status(rfq_id, "Supplier_Sourcing")
                            request_results = communication_service.request_part_quotes(
                                item.requested_part_number,
                                item.quantity,
                                condition_requested=item.condition_preference or "NE",
                                certification_requested=(
                                    self._requested_certification(rfq.raw_text)
                                    or "Applicable airworthiness certification"
                                ),
                                rfq_id=rfq_id,
                            )
                            db_service.add_audit_log(
                                rfq_id, "SupplierCommunicationAgent", "supplier_rfq_dispatch",
                                f"Part '{item.requested_part_number}' is not in the catalog; requested supplier quotations from {len(request_results)} contact(s).",
                                "PENDING" if operations_store.storage_engine == "postgresql" else "SUCCESS" if request_results else "WARNING",
                                json.dumps(request_results),
                            )
                        db_service.resolve_rfq_item(item.id, item.requested_part_number)
                        partsbase_request = await self._request_partsbase_quote(
                            rfq_id, item.requested_part_number, item.quantity
                        )
                        if partsbase_request.get("status") == "not_found":
                            return self._request_pn_verification(rfq, item.requested_part_number)
                        contact_queued = any(
                            result.get("transmission_status") in {"SENT", "PENDING", "QUEUED"}
                            for result in request_results
                        ) or partsbase_request.get("status") == "sent"
                        communication_service.send_rfq_sourcing_update(
                            recipient=rfq.customer_email,
                            customer_name=rfq.customer_name,
                            rfq_id=rfq_id,
                            part_number=item.requested_part_number,
                            reply_to=rfq.thread_id,
                            supplier_contact_queued=contact_queued,
                        )
                        return {
                            "status": "Supplier_Request_Sent" if contact_queued else "Supplier_Sourcing",
                            "message": (
                                f"Part '{item.requested_part_number}' is not in the internal catalog. "
                                + ("Supplier outreach was queued or submitted." if contact_queued else
                                   "No supplier request was queued; sourcing configuration requires review.")
                            ),
                            "supplier_request_count": len(request_results),
                            "supplier_requests": request_results,
                            "partsbase_request": partsbase_request,
                        }
                    invalid_format = (
                        res.escalation_triggered is not None
                        and res.escalation_triggered.condition == "invalid_part_format"
                    )
                    if not invalid_format:
                        return self._halt_retrieval_fault(
                            rfq_id, item.requested_part_number, "catalog",
                            RuntimeError(res.error_message or "Catalog retrieval failed"),
                        )
                    db_service.update_rfq_status(rfq_id, "Verification_Halted")
                    db_service.add_audit_log(
                        rfq_id, "PartsIntelligenceAgent", "part_validation",
                        f"Part verification halted for PN '{item.requested_part_number}': {res.error_message}",
                        "FAILURE", json.dumps(res.dict())
                    )
                    communication_service.send_rfq_update_reply(
                        recipient=rfq.customer_email, customer_name=rfq.customer_name, rfq_id=rfq_id,
                        customer_text="", original_subject=f"Request for quote {rfq_id}",
                        reply_to=rfq.thread_id,
                        inbound_message_id=f"invalid-pn:{item.requested_part_number}",
                        quote_answer=(
                            f"Please double-check P/N {item.requested_part_number}, including its full suffix. "
                            "We could not validate its format. Please provide the corrected part number "
                            "or a document identifying it so our team can review the request."
                        ),
                    )
                    operations_store.enqueue_operator_review(
                        idempotency_key=f"invalid-pn:{rfq_id}:{item.requested_part_number}",
                        task="catalog_part_validation", source_text=rfq.raw_text,
                        extraction={"rfq_id": rfq_id, "part_number": item.requested_part_number},
                        reason="invalid_part_number", entity_id=rfq_id,
                    )
                    return {
                        "status": "Verification_Halted", "diagnosis": "invalid_part_number",
                        "error": f"Part verification failed: {res.error_message}",
                        "escalation": res.escalation_triggered
                    }
                
                # Update item with resolved part number
                item.resolved_part_number = res.data["resolved_part_number"]
                
                db_service.add_audit_log(
                    rfq_id, "PartsIntelligenceAgent", "part_validation",
                    f"Resolved requested part '{item.requested_part_number}' to master MPN '{item.resolved_part_number}'.",
                    "SUCCESS", json.dumps(res.data)
                )
                
            rfq = db_service.update_rfq_status(rfq_id, "Inventory_Lookup")

        # 3. Inventory & Sourcing Check Stage
        if rfq.status == "Inventory_Lookup" or rfq.status == "Supplier_Sourcing":
            items = db_service.get_rfq_items(rfq_id)
            db_service.add_audit_log(rfq_id, "Orchestrator", "transition", "Checking internal inventory allocations.")

            for item in items:
                if item.id in allocated_sources:
                    continue

                # ── Query internal stock via InventoryAgent ──────────────────
                try:
                    inv_res = await self.inventory_agent.execute({
                        "part_number": item.resolved_part_number,
                        "requested_quantity": item.quantity
                    })
                    if not inv_res.success:
                        raise RuntimeError(inv_res.error_message or "Inventory retrieval failed")
                except Exception as exc:
                    return self._halt_retrieval_fault(rfq_id, item.resolved_part_number, "inventory", exc)

                inv_data = inv_res.data
                available_qty  = inv_data.get("available_quantity", 0)
                shortage_qty   = inv_data.get("shortage_quantity", item.quantity)
                avail_status   = inv_data.get("availability_status", "NOT_FOUND")

                # ── Escalate to supplier sourcing when stock is insufficient ──
                if inv_res.escalation_triggered and inv_res.escalation_triggered.condition == "stockout_detected":
                    db_service.add_audit_log(
                        rfq_id, "InventoryAgent", "stock_lookup",
                        (
                            f"Insufficient stock for '{item.resolved_part_number}'. "
                            f"Requested {item.quantity}, ATP available {available_qty} "
                            f"(status: {avail_status}). Shortage: {shortage_qty}. "
                            f"Activating supplier search."
                        ),
                        "WARNING", json.dumps(inv_data)
                    )

                    # Transition to supplier discovery
                    rfq = db_service.update_rfq_status(rfq_id, "Supplier_Sourcing")
                    try:
                        sup_res = await self.supplier_agent.execute({
                            "part_number": item.resolved_part_number,
                            "quantity_needed": shortage_qty
                        })
                    except Exception as exc:
                        return self._halt_retrieval_fault(rfq_id, item.resolved_part_number, "supplier", exc)

                    if not sup_res.success:
                        stale_offers = self.supplier_agent.last_stale_offers
                        if stale_offers:
                            confirmations = []
                            seen_suppliers = set()
                            for offer in stale_offers:
                                supplier_email = str(offer.get("supplier_email") or "").strip().lower()
                                if not supplier_email or supplier_email in seen_suppliers:
                                    continue
                                seen_suppliers.add(supplier_email)
                                confirmations.append(
                                    communication_service.request_stale_supplier_confirmation(
                                        recipient=supplier_email,
                                        supplier_name=str(offer.get("supplier_name") or "Supplier Team"),
                                        part_number=item.resolved_part_number,
                                        quantity=shortage_qty,
                                        reply_to=offer.get("source_email_id"),
                                        rfq_id=rfq_id,
                                    )
                                )
                            partsbase_request = await self._request_partsbase_quote(
                                rfq_id, item.resolved_part_number, item.quantity
                            )
                            db_service.add_audit_log(
                                rfq_id, "SupplierCommunicationAgent", "supplier_availability_confirmation",
                                f"Requested current availability from {len(confirmations)} supplier(s) using previous quote threads.",
                                "SUCCESS" if confirmations else "WARNING", json.dumps(confirmations),
                            )
                            historical_offer_date = next(
                                (
                                    str(offer.get("updated_at")).split("T", 1)[0]
                                    for offer in stale_offers if offer.get("updated_at")
                                ),
                                None,
                            )
                            communication_service.send_rfq_sourcing_update(
                                recipient=rfq.customer_email,
                                customer_name=rfq.customer_name,
                                rfq_id=rfq_id,
                                part_number=item.resolved_part_number,
                                reply_to=rfq.thread_id,
                                historical_offer_date=historical_offer_date,
                                indicative_unit_price=self._historical_reference_price(stale_offers, item.quantity),
                                supplier_contact_queued=any(
                                    result.get("transmission_status") in {"SENT", "PENDING", "QUEUED"}
                                    for result in confirmations
                                ) or partsbase_request.get("status") == "sent",
                            )
                            db_service.update_rfq_status(rfq_id, "Supplier_Confirmation_Requested")
                            return {
                                "status": "Supplier_Confirmation_Requested",
                                "error": f"All stored supplier quotes for '{item.resolved_part_number}' are older than 30 days.",
                                "supplier_confirmation_count": len(confirmations),
                                "supplier_confirmations": confirmations,
                                "partsbase_request": partsbase_request,
                            }
                        transaction = operations_store.transaction() if operations_store.storage_engine == "postgresql" else nullcontext()
                        with transaction:
                            request_results = communication_service.request_part_quotes(
                                item.resolved_part_number,
                                shortage_qty,
                                condition_requested=item.condition_preference or "NE",
                                certification_requested=self._requested_certification(rfq.raw_text),
                                rfq_id=rfq_id,
                            )
                            db_service.update_rfq_status(rfq_id, "Sourcing_Failed")
                            db_service.add_audit_log(
                                rfq_id, "SupplierDiscoveryAgent", "supplier_search",
                                f"Failed to source part '{item.resolved_part_number}': {sup_res.error_message}",
                                "FAILURE", json.dumps(sup_res.dict())
                            )
                            db_service.add_audit_log(
                                rfq_id, "SupplierCommunicationAgent", "supplier_rfq_dispatch",
                                f"Requested quotations for unavailable part '{item.resolved_part_number}' from {len(request_results)} supplier contact(s).",
                                "PENDING" if operations_store.storage_engine == "postgresql" else "SUCCESS" if request_results else "WARNING",
                                json.dumps(request_results),
                            )
                        partsbase_request = await self._request_partsbase_quote(
                            rfq_id, item.resolved_part_number, item.quantity
                        )
                        if partsbase_request.get("status") == "not_found":
                            db_service.update_rfq_status(rfq_id, "Supplier_Sourcing")
                            return self._request_pn_verification(rfq, item.resolved_part_number)
                        communication_service.send_rfq_sourcing_update(
                            recipient=rfq.customer_email,
                            customer_name=rfq.customer_name,
                            rfq_id=rfq_id,
                            part_number=item.resolved_part_number,
                            reply_to=rfq.thread_id,
                            supplier_contact_queued=any(
                                result.get("transmission_status") in {"SENT", "PENDING", "QUEUED"}
                                for result in request_results
                            ) or partsbase_request.get("status") == "sent",
                        )
                        return {
                            "status": "Sourcing_Failed",
                            "error": f"Sourcing failed: {sup_res.error_message}",
                            "supplier_request_count": len(request_results),
                            "supplier_requests": request_results,
                            "partsbase_request": partsbase_request,
                            "escalation": sup_res.escalation_triggered
                        }

                    # Select best supplier quote (lowest price, already sorted in agent)
                    best_quote = sup_res.data["supplier_quotes"][0]
                    allocated_sources[item.id] = {
                        "source": "Supplier",
                        "unit_cost": best_quote["unit_cost"],
                        "details": best_quote,
                        "certificate_type": best_quote["certificate_type"],
                        "has_full_trace": bool(best_quote.get("trace_documents")),
                    }
                    pipeline_state = self._save_pipeline_state(
                        rfq_id, allocated_sources=allocated_sources
                    )

                    db_service.add_audit_log(
                        rfq_id, "SupplierDiscoveryAgent", "supplier_search",
                        f"Allocated sourcing for '{item.resolved_part_number}' from {best_quote['supplier_name']} at cost ${best_quote['unit_cost']:.2f}.",
                        "SUCCESS", json.dumps(best_quote)
                    )

                else:
                    # ── Fully satisfied from internal warehouse inventory ───────
                    allocated_sources[item.id] = {
                        "source": "Inventory",
                        "unit_cost": inv_data.get("unit_cost", 0.0),
                        "details": {
                            "condition":        inv_data.get("condition"),
                            "warehouse":        inv_data.get("warehouse"),
                            "lead_time":        inv_data.get("lead_time"),
                            "available_quantity": available_qty,
                            "trace_documents": inv_data.get("trace_documents") or [],
                        },
                        "certificate_type": inv_data.get("certificate_type", "None"),
                        "has_full_trace":   inv_data.get("has_full_trace", False),
                    }
                    pipeline_state = self._save_pipeline_state(
                        rfq_id, allocated_sources=allocated_sources
                    )
                    db_service.add_audit_log(
                        rfq_id, "InventoryAgent", "stock_lookup",
                        (
                            f"Allocated {item.quantity} units for '{item.resolved_part_number}' "
                            f"from {inv_data.get('warehouse', 'warehouse')} "
                            f"(ATP: {available_qty}, status: {avail_status})."
                        ),
                        "SUCCESS", json.dumps(inv_data)
                    )

            rfq = db_service.update_rfq_status(rfq_id, "Compliance_Check")

        # 4. Compliance Auditing Stage
        if rfq.status == "Compliance_Check":
            db_service.add_audit_log(rfq_id, "Orchestrator", "transition", "Running regulatory compliance checks.")
            items = db_service.get_rfq_items(rfq_id)
            missing_allocations = [
                item.id for item in items if item.id not in allocated_sources
            ]
            if missing_allocations:
                message = (
                    "Cannot resume compliance checks because saved source allocations "
                    "are missing for one or more RFQ items."
                )
                db_service.add_audit_log(
                    rfq_id, "Orchestrator", "pipeline_resume_blocked", message,
                    "FAILURE", json.dumps({"missing_item_ids": missing_allocations}),
                )
                return {"status": rfq.status, "error": message}
            
            for item in items:
                source_details = allocated_sources.get(item.id, {})
                comp_res = await self.compliance_agent.execute({
                    "part_number": item.resolved_part_number,
                    "source": source_details.get("source"),
                    "supplier_name": source_details.get("details", {}).get("supplier_name", "Winged Tycoons Internal"),
                    "certificate_type": source_details.get("certificate_type"),
                    "has_full_trace": source_details.get("has_full_trace", False),
                    "trace_documents": source_details.get("details", {}).get("trace_documents") or [],
                    "supplier_approved": (
                        source_details.get("details", {}).get("approval_status") == "Approved"
                        if source_details.get("source") == "Supplier"
                        else None
                    ),
                    "certificate_status": source_details.get("details", {}).get("certificate_status"),
                    "expiration_date": source_details.get("details", {}).get("expiration_date"),
                    "requested_certificate_type": self._requested_certification(rfq.raw_text),
                    "requested_condition": item.condition_preference,
                    "condition": source_details.get("details", {}).get("condition") or item.condition_preference,
                })
                
                source_details["compliance_status"] = comp_res.data.get("compliance_status", "Pass")
                pipeline_state = self._save_pipeline_state(
                    rfq_id, allocated_sources=allocated_sources
                )
                
                compliance_status = comp_res.data.get("compliance_status")
                if compliance_status != "APPROVED":
                    review_required = compliance_status == "HUMAN_REVIEW_REQUIRED"
                    rfq_status = "Compliance_Warning" if review_required else "Compliance_Blocked"
                    db_service.update_rfq_status(rfq_id, rfq_status)
                    db_service.add_audit_log(
                        rfq_id, "ComplianceAgent", "compliance_audit",
                        f"Compliance check for '{item.resolved_part_number}' requires "
                        f"{'human review' if review_required else 'blocking'}: "
                        f"{', '.join(comp_res.data.get('issues_detected', []))}",
                        "WARNING" if review_required else "FAILURE",
                        json.dumps(comp_res.model_dump(mode="json"))
                    )
                    return {
                        "status": rfq_status,
                        "error": (
                            "Compliance review required before pricing or customer communication."
                            if review_required
                            else f"Compliance Blocked: {comp_res.error_message}"
                        ),
                        "escalation": comp_res.escalation_triggered
                    }
                
                db_service.add_audit_log(
                    rfq_id, "ComplianceAgent", "compliance_audit",
                    f"Passed compliance review for '{item.resolved_part_number}'. No major risks identified.",
                    "SUCCESS", json.dumps(comp_res.data)
                )
                
            rfq = db_service.update_rfq_status(rfq_id, "Pricing")

        # 5. Pricing Calculation Stage
        quote_items_draft = []
        shipping_total = 0.0
        
        if rfq.status == "Pricing":
            db_service.add_audit_log(rfq_id, "Orchestrator", "transition", "Executing pricing margins engine.")
            items = db_service.get_rfq_items(rfq_id)
            missing_allocations = [
                item.id for item in items if item.id not in allocated_sources
            ]
            if missing_allocations:
                message = (
                    "Cannot safely resume pricing because saved source allocations "
                    "are missing for one or more RFQ items."
                )
                db_service.add_audit_log(
                    rfq_id, "Orchestrator", "pipeline_resume_blocked", message,
                    "FAILURE", json.dumps({"missing_item_ids": missing_allocations}),
                )
                return {"status": rfq.status, "error": message}
            
            has_low_margin_escalation = False
            margin_esc_rule = None
            
            for item in items:
                source_details = allocated_sources.get(item.id, {})
                p_data, low_margin = self.calculate_pricing(
                    float(source_details.get("unit_cost", 0.0)),
                    int(item.quantity),
                )
                
                # Check low-margin warning
                if low_margin:
                    has_low_margin_escalation = True
                    margin_esc_rule = self.pricing_agent.metadata.escalation_rules[0]
                    db_service.add_audit_log(
                        rfq_id, "PricingAgent", "pricing_calc",
                        f"Low margin warning on item '{item.resolved_part_number}': Margin is {p_data.get('margin_percent')}% (below 10%).",
                        "WARNING", json.dumps({"data": p_data, "escalation_triggered": margin_esc_rule.model_dump()})
                    )
                else:
                    db_service.add_audit_log(
                        rfq_id, "PricingAgent", "pricing_calc",
                        f"Calculated customer pricing for '{item.resolved_part_number}': Unit Cost: ${p_data['unit_cost']:.2f}, Unit Sell: ${p_data['suggested_unit_price']:.2f} ({p_data['margin_percent']}% margin).",
                        "SUCCESS", json.dumps(p_data)
                    )
                
                quote_items_draft.append({
                    "rfq_item_id": item.id,
                    "part_number": item.resolved_part_number,
                    "description": item.resolved_part_number,
                    "quantity": item.quantity,
                    "uom": getattr(item, "uom", "EA"),
                    "unit_price": p_data["suggested_unit_price"],
                    "source": source_details.get("source"),
                    "certificate_type": source_details.get("certificate_type"),
                    "condition": getattr(item, "condition_preference", None),
                    "lead_time_days": _lead_time_days(
                        source_details.get("details", {}).get("lead_time")
                        or source_details.get("details", {}).get("lead_time_days")
                    ),
                    "unit_cost": p_data["unit_cost"],
                    "margin_percent": p_data["margin_percent"],
                    "compliance_status": source_details.get("compliance_status", "Pass"),
                    "attachments": getattr(item, "attachments", []),
                    "source_email_id": source_details.get("details", {}).get("source_email_id"),
                    "warranty_terms": source_details.get("details", {}).get("warranty_terms"),
                    "trace_documents": source_details.get("details", {}).get("trace_documents") or [],
                })
                
            context = {
                "quote_items_draft": quote_items_draft,
                "shipping_total": 0.0,
                "has_low_margin_escalation": has_low_margin_escalation,
                "margin_esc_rule": margin_esc_rule
            }
            if margin_esc_rule is not None and hasattr(margin_esc_rule, "model_dump"):
                context["margin_esc_rule"] = margin_esc_rule.model_dump(mode="json")
            self._save_pipeline_state(rfq_id, quote_generation=context)
            rfq = db_service.update_rfq_status(rfq_id, "Quote_Generation")
        elif rfq.status == "Quote_Generation":
            context = pipeline_state.get("quote_generation")
            if not isinstance(context, dict) or not isinstance(
                context.get("quote_items_draft"), list
            ):
                message = (
                    "Cannot resume quote generation because the saved pricing draft "
                    "is missing. Return this RFQ to operator review before continuing."
                )
                db_service.add_audit_log(
                    rfq_id, "Orchestrator", "pipeline_resume_blocked", message, "FAILURE"
                )
                return {"status": rfq.status, "error": message}
        else:
            return {"status": rfq.status, "message": "RFQ is not in a pricing-ready state."}

        # 6. Quote Proposal Generation Stage
        if rfq.status == "Quote_Generation":
            db_service.add_audit_log(rfq_id, "Orchestrator", "transition", "Assembling formal Quote proposal document.")
            
            draft_items = context["quote_items_draft"]
            ship_cost = 0.0
            
            q_res = await self.quote_agent.execute({
                "rfq_id": rfq_id,
                "quote_items": draft_items,
                "shipping_cost": ship_cost
            })
            
            q_data = q_res.data
            # Save Quote inside db_service
            quote = db_service.create_quote(
                rfq_id=rfq_id,
                subtotal=q_data["subtotal"],
                shipping=q_data["shipping_cost"],
                total=q_data["total_amount"],
                lead_time_days=min((item.get("lead_time_days") or 0 for item in draft_items), default=None),
                valid_until=(datetime.now(timezone.utc) + timedelta(days=int(q_data.get("quote_validity_days", 30)))).date().isoformat(),
            )
            
            # Save items
            for item in draft_items:
                db_service.add_quote_item(
                    quote_id=quote.id,
                    rfq_item_id=item["rfq_item_id"],
                    part_number=item["part_number"],
                    qty=item["quantity"],
                    source=item["source"],
                    unit_cost=item["unit_cost"],
                    unit_price=item["unit_price"],
                    margin=item["margin_percent"],
                    cert=item["certificate_type"],
                    comp_status=item["compliance_status"],
                    uom=item.get("uom", "EA"),
                    attachments=item.get("attachments", [])
                    ,description=item.get("description", item["part_number"])
                    ,condition=item.get("condition")
                    ,lead_time_days=item.get("lead_time_days")
                    ,source_email_id=item.get("source_email_id")
                    ,warranty_terms=item.get("warranty_terms")
                    ,trace_documents=item.get("trace_documents")
                )
                
            # Log success
            db_service.add_audit_log(
                rfq_id, "QuoteGenerationAgent", "quote_assembly",
                f"Generated formal Quote draft '{quote.id}' with total value ${quote.total_amount:.2f}.",
                "SUCCESS", json.dumps(q_data)
            )
            
            # A quote is not marked sent until the outbox confirms external delivery.
            if operations_store.storage_engine != "postgresql":
                db_service.update_quote_status(quote.id, "Pending_Dispatch")
                db_service.update_rfq_status(rfq_id, "Quote_Dispatch_Pending")
            communication_result = await self._dispatch_customer_quote(rfq, quote)
            if not communication_result.success:
                db_service.update_rfq_status(rfq_id, "Quote_Dispatch_Failed")
                return {
                    "status": "Quote_Dispatch_Failed",
                    "quote_id": quote.id,
                    "error": communication_result.error_message,
                }

            transmission_status = communication_result.data.get("transmission_status", "UNKNOWN")
            if transmission_status != "SENT":
                db_service.add_audit_log(
                    rfq_id, "CustomerCommunicationAgent", "email_dispatch_queued",
                    f"Customer quote email delivery state: {transmission_status}.",
                    "PENDING", json.dumps(communication_result.data),
                )
                return {
                    "status": "Quote_Dispatch_Pending",
                    "quote_id": quote.id,
                    "transmission_status": transmission_status,
                    "email_body": communication_result.data.get("formatted_body"),
                }

            db_service.update_quote_status(quote.id, "Sent")
            db_service.update_rfq_status(rfq_id, "Quote_Sent")

            status = "Quote_Sent"
            if context["has_low_margin_escalation"]:
                margin_rule_payload = (
                    context["margin_esc_rule"].model_dump()
                    if hasattr(context["margin_esc_rule"], "model_dump")
                    else context["margin_esc_rule"]
                )
                db_service.add_audit_log(
                    rfq_id, "PricingAgent", "low_margin_autonomous_dispatch",
                    "Quote dispatched autonomously despite low-margin escalation; PO review remains human-gated.",
                    "WARNING", json.dumps(margin_rule_payload),
                )
            db_service.add_audit_log(
                rfq_id, "CustomerCommunicationAgent", "email_dispatch",
                f"Autonomous quote email dispatched to customer '{rfq.customer_name}'.",
                "SUCCESS", json.dumps(communication_result.data),
            )
            return {"status": status, "quote_id": quote.id, "email_body": communication_result.data.get("formatted_body")}

    async def _record_quote_policy_advisory(
        self, rfq_id: str, quote: Any, items: list, *, repositories=None,
        operator_name: str | None = None,
    ) -> dict:
        def value(record, name):
            return record.get(name) if isinstance(record, dict) else getattr(record, name, None)

        facts = {
            "quote_id": value(quote, "id"),
            "total_amount": value(quote, "total_amount"),
            "quote_status": value(quote, "status"),
            "operator_name": operator_name,
            "dispatch_authority": "existing_backend_approval_workflow",
            "items": [{
                "part_number": value(item, "part_number"),
                "quantity": value(item, "quantity"),
                "unit_cost": value(item, "unit_cost"),
                "unit_price": value(item, "unit_price"),
                "margin_percent": value(item, "margin_percent"),
                "compliance_status": value(item, "compliance_status"),
            } for item in items],
            "extraction_confidence": value(quote, "extraction_confidence"),
            "sanctions_clear": value(quote, "sanctions_clear"),
        }
        advisory = await email_program_runtime.evaluate_policy(facts)
        audit = {
            "rfq_id": rfq_id,
            "agent_name": "PolicyEvaluation",
            "action_type": "quote_policy_advisory",
            "message": f"Advisory policy evaluation: {advisory['status']}; dispatch authority is unchanged.",
            "status": "WARNING" if advisory["status"] == "unavailable" else "INFO",
            "payload_json": json.dumps(advisory),
        }
        if repositories is None:
            db_service.add_audit_log(
                rfq_id, audit["agent_name"], audit["action_type"], audit["message"],
                audit["status"], audit["payload_json"],
            )
        else:
            await repositories.rfq.add_audit_log(**audit)
        return advisory

    async def _dispatch_customer_quote(self, rfq: Any, quote: Any) -> AgentResponse:
        quote_items = db_service.get_quote_items(quote.id)
        await self._record_quote_policy_advisory(rfq.id, quote, quote_items)
        try:
            transmission = communication_service.send_customer_quote(
                recipient=rfq.customer_email,
                customer_name=rfq.customer_name,
                quote_id=quote.id,
                quote_summary=f"Approved quote {quote.id}; total ${float(quote.total_amount or 0):,.2f}.",
                reply_to=rfq.thread_id,
                quote_items=quote_items,
            )
        except Exception as exc:
            logger.exception("Customer quote dispatch failed rfq=%s quote=%s", rfq.id, quote.id)
            return AgentResponse(
                success=False,
                error_message=f"Customer email delivery failed: {type(exc).__name__}: {exc}",
            )
        body, _ = communication_service.render_customer_quote_email(
            customer_name=rfq.customer_name,
            quote_id=quote.id,
            quote=quote,
            items=quote_items,
        )
        return AgentResponse(success=True, data={
            "communication_logged": True,
            "transmission_status": transmission["transmission_status"],
            "formatted_body": body,
            "subject": transmission["subject"],
        })

    async def approve_and_queue_quote_async(
        self,
        repositories,
        quote_id: str,
        operator_name: str,
        overrides: Optional[List[Dict[str, Any]]] = None,
        comments: Optional[str] = None,
        expected_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        quote_payload = await repositories.records.get("quotes", quote_id)
        if quote_payload is None:
            return {"error": f"Quote {quote_id} not found.", "status_code": 404}
        if quote_payload.get("status") in {"Approved", "Pending_Dispatch", "Dispatch_Pending", "Sent"}:
            return {"error": f"Quote {quote_id} has already been approved or dispatched."}

        rfq_id = str(quote_payload.get("rfq_id") or "")
        rfq = await db_service.get_rfq_async(repositories, rfq_id)
        if rfq is None:
            return {"error": f"RFQ {rfq_id} not found.", "status_code": 404}
        if quote_payload.get("status") == "Sent" or rfq.status == "Quote_Sent":
            return {
                "status": "Quote_Sent",
                "quote_id": quote_id,
                "message": "Quote was already dispatched autonomously.",
            }

        quote_items = list((await repositories.records.list_by_payload_value(
            "quote_items", "quote_id", quote_id
        )).values())
        quote_items.sort(key=lambda item: str(item.get("id") or ""))
        if not quote_items:
            return {"error": "Persisted quote item data is required before dispatch."}

        requested_overrides = overrides or []
        override_map = {str(item.get("quote_item_id")): float(item["unit_price"]) for item in requested_overrides}
        if len(override_map) != len(requested_overrides):
            return {"error": "Each quote item can be overridden only once."}
        item_ids = {str(item.get("id")) for item in quote_items}
        if set(override_map) - item_ids:
            return {"error": "An override references an item outside this quote."}

        updated_items = []
        override_audit_messages = []
        for original in quote_items:
            item = dict(original)
            item_id = str(item.get("id"))
            if item_id in override_map:
                unit_price = override_map[item_id]
                unit_cost = float(item.get("unit_cost") or 0)
                margin = round(((unit_price - unit_cost) / unit_price) * 100, 2) if unit_price else 0.0
                item["unit_price"] = unit_price
                item["margin_percent"] = margin
                override_audit_messages.append(
                    f"Operator override on item '{item.get('part_number', '')}': "
                    f"set price to ${unit_price:.2f} (new margin {margin}%)."
                )
            updated_items.append(item)

        quote_payload = dict(quote_payload)
        if requested_overrides:
            subtotal = round(sum(
                int(item.get("quantity") or 0) * float(item.get("unit_price") or 0)
                for item in updated_items
            ), 2)
            quote_payload["subtotal"] = subtotal
            quote_payload["total_amount"] = round(
                subtotal + float(quote_payload.get("shipping_cost") or 0), 2
            )
        version = int(quote_payload.get("version") or 1)
        if expected_version is not None and expected_version != version:
            return {"error": f"Quote {quote_id} was updated by another operation."}

        quote_details = {
            "quote_id": quote_id,
            "subtotal": quote_payload.get("subtotal", quote_payload.get("total_amount", 0)),
            "shipping_cost": quote_payload.get("shipping_cost", 0),
            "total_amount": quote_payload.get("total_amount", 0),
            "items": [{
                "part_number": item.get("part_number", ""),
                "quantity": item.get("quantity", 0),
                "uom": item.get("uom", "EA"),
                "unit_price": item.get("unit_price", 0),
                "attachments": item.get("attachments", []),
            } for item in updated_items],
        }
        draft_result = await self.comm_agent.execute({
            "customer_email": rfq.customer_email,
            "customer_name": rfq.customer_name,
            "company_name": rfq.customer_name,
            "communication_sentiment": self._load_pipeline_state(rfq.id).get("communication_sentiment"),
            "quote_details": quote_details,
            "reply_to": rfq.thread_id,
        }, context={"draft_only": True})
        if draft_result.success:
            draft = draft_result.data
            await repositories.records.record_llm_telemetry(**dict(draft["telemetry"]))
            await repositories.records.record_automation_event(**draft["automation_event"])
        else:
            draft = {}
            await repositories.rfq.add_audit_log(
                rfq_id=rfq_id,
                agent_name="CustomerCommunicationAgent",
                action_type="quote_email_draft_skipped",
                message=(
                    "The generated draft was unavailable; the customer email will use the "
                    "verified quote record and deterministic template."
                ),
                status="WARNING",
                payload_json=json.dumps({"error": draft_result.error_message}),
            )

        await self._record_quote_policy_advisory(
            rfq_id, {**quote_payload, "id": quote_id}, updated_items,
            repositories=repositories, operator_name=operator_name,
        )
        if not await repositories.quote.approve_for_dispatch(
            quote_id=quote_id,
            rfq_id=rfq_id,
            expected_version=version,
            operator_name=operator_name,
            comments=comments,
            quote_payload=quote_payload,
            item_payloads=updated_items,
            override_audit_messages=override_audit_messages,
        ):
            return {"error": f"Quote {quote_id} is no longer awaiting approval."}

        rendered_body, rendered_html = communication_service.render_customer_quote_email(
            customer_name=rfq.customer_name,
            quote_id=quote_id,
            quote={
                "shipping_cost": quote_payload.get("shipping_cost", 0),
                "total_amount": quote_payload.get("total_amount", 0),
                "valid_until": quote_payload.get("valid_until"),
            },
            items=updated_items,
        )
        transmission = await communication_service.enqueue_customer_quote_async(
            repositories,
            recipient=rfq.customer_email,
            quote_id=quote_id,
            rfq_id=rfq_id,
            subject=f"Winged Tycoons quotation {quote_id}",
            body=rendered_body,
            html_body=rendered_html,
            quote_items=updated_items,
            reply_to=rfq.thread_id,
        )
        await communication_service.schedule_customer_followups_async(
            repositories,
            recipient=rfq.customer_email,
            customer_name=rfq.customer_name,
            quote_id=quote_id,
            part_number=str(updated_items[0].get("part_number") or "the quoted part"),
            reply_to=rfq.thread_id,
        )
        await repositories.rfq.session.flush()
        return {
            "status": "Quote_Dispatch_Pending",
            "quote_id": quote_id,
            "transmission_status": transmission["transmission_status"],
            "email_body": rendered_body,
        }

    async def approve_and_send_quote(
        self,
        quote_id: str,
        operator_name: str,
        overrides: Optional[List[Dict[str, Any]]] = None,
        comments: Optional[str] = None,
        expected_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Processes human approval. Overrides prices if supplied, recalculates totals,
        and fires Customer Communication transmission.
        """
        quote = db_service.get_quote(quote_id)
        if not quote:
            return {"error": f"Quote {quote_id} not found."}

        if quote.status in {"Approved", "Pending_Dispatch", "Dispatch_Pending", "Sent"}:
            return {"error": f"Quote {quote_id} has already been approved or dispatched."}

        expected_version = quote.version if expected_version is None else expected_version
            
        rfq_id = quote.rfq_id

        if quote.status == "Sent" or (db_service.get_rfq(rfq_id) and db_service.get_rfq(rfq_id).status == "Quote_Sent"):
            return {"status": "Quote_Sent", "quote_id": quote_id, "message": "Quote was already dispatched autonomously."}
        
        # Apply overrides if provided
        if overrides:
            items = db_service.get_quote_items(quote_id)
            new_subtotal = 0.0
            for item in items:
                for over in overrides:
                    if over.get("quote_item_id") == item.id:
                        item.unit_price = over["unit_price"]
                        item.margin_percent = round(((item.unit_price - item.unit_cost) / item.unit_price) * 100, 2)
                        db_service.add_audit_log(
                            rfq_id, "Orchestrator", "human_override",
                            f"Operator override on item '{item.part_number}': set price to ${item.unit_price:.2f} (new margin {item.margin_percent}%).",
                            "SUCCESS"
                        )
                new_subtotal += item.quantity * item.unit_price
            quote.subtotal = round(new_subtotal, 2)
            quote.total_amount = round(quote.subtotal + quote.shipping_cost, 2)
            
        db_service.update_quote_status(
            quote_id,
            "Approved" if operations_store.storage_engine == "postgresql" else "Pending_Dispatch",
            approved_by=operator_name,
            expected_version=expected_version,
        )
        current_rfq = db_service.get_rfq(rfq_id)
        if (
            operations_store.storage_engine != "postgresql"
            and current_rfq
            and current_rfq.status != "Quote_Dispatch_Pending"
        ):
            db_service.update_rfq_status(rfq_id, "Quote_Dispatch_Pending")
        db_service.add_audit_log(
            rfq_id, "Orchestrator", "human_approval",
            f"Quote {quote_id} approved by commercial operator '{operator_name}'."
            + (f" Comments: {comments}" if comments else ""),
            "SUCCESS"
        )
        
        # Render commercial details only from the persisted quote record.
        rfq = db_service.get_rfq(rfq_id)
        quote_items = db_service.get_quote_items(quote_id)
        await self._record_quote_policy_advisory(
            rfq_id, quote, quote_items, operator_name=operator_name,
        )
        try:
            transmission = communication_service.send_customer_quote(
                recipient=rfq.customer_email,
                customer_name=rfq.customer_name,
                quote_id=quote_id,
                quote_summary=f"Approved quote {quote_id}; total ${float(quote.total_amount or 0):,.2f}.",
                reply_to=rfq.thread_id,
                quote_items=quote_items,
            )
            rendered_body, _ = communication_service.render_customer_quote_email(
                customer_name=rfq.customer_name,
                quote_id=quote_id,
                quote=quote,
                items=quote_items,
            )
            comm_res = AgentResponse(success=True, data={
                "transmission_status": transmission["transmission_status"],
                "formatted_body": rendered_body,
                "subject": transmission["subject"],
            })
        except Exception as exc:
            logger.exception("Approved customer quote dispatch failed quote=%s", quote_id)
            comm_res = AgentResponse(
                success=False,
                error_message=f"Customer email delivery failed: {type(exc).__name__}: {exc}",
            )

        if not comm_res.success:
            db_service.update_quote_status(quote_id, "Dispatch_Failed", comments=comm_res.error_message)
            db_service.update_rfq_status(rfq_id, "Quote_Dispatch_Failed")
            return {"error": comm_res.error_message, "status": "Quote_Dispatch_Failed"}

        transmission_status = comm_res.data.get("transmission_status", "UNKNOWN")
        if transmission_status != "SENT":
            db_service.add_audit_log(
                rfq_id, "CustomerCommunicationAgent", "email_dispatch_queued",
                f"Operator-approved quote email delivery state: {transmission_status}.",
                "PENDING", json.dumps(comm_res.data),
            )
            return {"status": "Quote_Dispatch_Pending", "quote_id": quote_id,
                    "transmission_status": transmission_status,
                    "email_body": comm_res.data.get("formatted_body")}

        db_service.update_quote_status(quote_id, "Sent", comments=comments)
        db_service.update_rfq_status(rfq_id, "Quote_Sent")
        
        db_service.add_audit_log(
            rfq_id, "CustomerCommunicationAgent", "email_dispatch",
            f"Sales proposal email successfully sent to customer '{rfq.customer_name}' at {rfq.customer_email}.",
            "SUCCESS", json.dumps(comm_res.data)
        )
        
        return {
            "status": "Quote_Sent",
            "quote_id": quote_id,
            "email_body": comm_res.data["formatted_body"]
        }

orchestration_service = OrchestrationService()
