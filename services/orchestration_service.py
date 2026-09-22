import json
import re
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


def _lead_time_days(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None


def _is_partsbase_rfq(rfq: Any) -> bool:
    source = f"{getattr(rfq, 'customer_email', '')} {getattr(rfq, 'raw_text', '')}".lower()
    return "partsbase.com" in source

class OrchestrationService:
    def __init__(self):
        self.intake_agent = RFQIntakeAgent()
        self.parts_intel_agent = PartsIntelligenceAgent()
        self.inventory_agent = InventoryAgent()
        self.supplier_agent = SupplierDiscoveryAgent()
        self.compliance_agent = ComplianceAgent()
        self.pricing_agent = PricingAgent()
        self.quote_agent = QuoteGenerationAgent()
        self.comm_agent = CustomerCommunicationAgent()

    @staticmethod
    def _requested_certification(raw_text: str) -> str:
        text = (raw_text or "").lower()
        if "easa form 1" in text:
            return "EASA Form 1"
        if "coc" in text or "certificate of conformity" in text:
            return "CoC"
        if "8130" in text:
            return "FAA 8130-3"
        return "Applicable airworthiness certification"

    async def process_rfq_pipeline(self, rfq_id: str) -> Dict[str, Any]:
        """
        Executes the RFQ automated pipeline.
        Steps: Intake -> Validate -> Inventory -> Supplier Sourcing -> Compliance -> Pricing -> Quote Gen.
        Halts on any validation issues, compliance blocks, or pricing anomalies.
        """
        rfq = db_service.get_rfq(rfq_id)
        if not rfq:
            return {"error": f"RFQ {rfq_id} not found."}
        if rfq.automation_paused:
            return {
                "status": "Automation_Paused",
                "rfq_id": rfq_id,
                "reason": rfq.pause_reason or "Paused by an operator.",
            }

        # 1. RFQ Intake Check
        if rfq.status == "Intake":
            db_service.add_audit_log(rfq_id, "Orchestrator", "transition", "Starting RFQ Intake processing stage.")
            res = await self.intake_agent.execute({"raw_text": rfq.raw_text})
            
            if not res.success:
                intake_data = res.data or {}
                requires_internal_review = (
                    intake_data.get("AOG_status") is True
                    or intake_data.get("priority") in {"AOG", "Urgent"}
                )
                if requires_internal_review:
                    db_service.update_rfq_customer(
                        rfq_id,
                        intake_data.get("customer_name") or intake_data.get("company"),
                        intake_data.get("customer_email"),
                    )
                    for item in intake_data.get("items", []):
                        requested_part = item.get("requested_part_number")
                        if requested_part:
                            db_service.add_rfq_item(
                                rfq_id=rfq_id,
                                requested_part=requested_part,
                                qty=item.get("quantity", 1),
                                uom=item.get("uom", "EA"),
                                aircraft=item.get("aircraft_type"),
                                condition=item.get("condition_preference", "NE"),
                            )
                    db_service.update_rfq_status(rfq_id, "Pending_Internal_Review")
                    db_service.add_audit_log(
                        rfq_id,
                        "RFQIntakeAgent",
                        "intake_review",
                        f"AOG/urgent RFQ requires internal review: {res.error_message}",
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
            db_service.update_rfq_customer(
                rfq_id,
                res.data.get("customer_name") or res.data.get("company"),
                res.data.get("customer_email"),
            )
            for item in items_data:
                db_service.add_rfq_item(
                    rfq_id=rfq_id,
                    requested_part=item["requested_part_number"],
                    qty=item["quantity"],
                    uom=item.get("uom", "EA"),
                    aircraft=item.get("aircraft_type"),
                    condition=item.get("condition_preference", "NE")
                )
            
            # Log success and update status
            db_service.add_audit_log(
                rfq_id, "RFQIntakeAgent", "intake_parse",
                f"Successfully parsed customer request from {res.data.get('customer_name')}. Extracted {len(items_data)} items.",
                "SUCCESS", json.dumps(res.data)
            )
            rfq = db_service.update_rfq_status(rfq_id, "Validating")

        # 2. Part Catalog Validation Stage
        if rfq.status == "Validating":
            db_service.add_audit_log(rfq_id, "Orchestrator", "transition", "Starting part number catalog validation.")
            items = db_service.get_rfq_items(rfq_id)
            
            for item in items:
                res = await self.parts_intel_agent.execute({"requested_part_number": item.requested_part_number})
                
                if not res.success:
                    unknown_part = "unknown" in (res.error_message or "").lower() or "not found" in (res.error_message or "").lower()
                    if unknown_part:
                        request_results = communication_service.request_part_quotes(
                            item.requested_part_number,
                            item.quantity,
                            condition_requested=item.condition_preference or "NE",
                            certification_requested=self._requested_certification(rfq.raw_text),
                        )
                        db_service.update_rfq_status(rfq_id, "Supplier_Sourcing")
                        db_service.add_audit_log(
                            rfq_id, "SupplierCommunicationAgent", "supplier_rfq_dispatch",
                            f"Part '{item.requested_part_number}' is not in the catalog; requested supplier quotations from {len(request_results)} contact(s).",
                            "SUCCESS" if request_results else "WARNING",
                            json.dumps(request_results),
                        )
                        return {
                            "status": "Supplier_Request_Sent",
                            "message": f"Part '{item.requested_part_number}' is not in the internal catalog. Supplier outreach was initiated.",
                            "supplier_request_count": len(request_results),
                            "supplier_requests": request_results,
                        }
                    db_service.update_rfq_status(rfq_id, "Verification_Halted")
                    db_service.add_audit_log(
                        rfq_id, "PartsIntelligenceAgent", "part_validation",
                        f"Part verification halted for PN '{item.requested_part_number}': {res.error_message}",
                        "FAILURE", json.dumps(res.dict())
                    )
                    return {
                        "status": "Verification_Halted", 
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
        allocated_sources = {}  # item_id -> {source, unit_cost, certificate_type, has_full_trace, details}

        if rfq.status == "Inventory_Lookup" or rfq.status == "Supplier_Sourcing":
            items = db_service.get_rfq_items(rfq_id)
            db_service.add_audit_log(rfq_id, "Orchestrator", "transition", "Checking internal inventory allocations.")

            for item in items:
                # ── Query internal stock via InventoryAgent ──────────────────
                inv_res = await self.inventory_agent.execute({
                    "part_number": item.resolved_part_number,
                    "requested_quantity": item.quantity
                })

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
                    sup_res = await self.supplier_agent.execute({
                        "part_number": item.resolved_part_number,
                        "quantity_needed": shortage_qty  # only the unmet quantity
                    })

                    if not sup_res.success:
                        request_results = communication_service.request_part_quotes(
                            item.resolved_part_number,
                            shortage_qty,
                            condition_requested=item.condition_preference or "NE",
                            certification_requested=self._requested_certification(rfq.raw_text),
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
                            "SUCCESS" if request_results else "WARNING",
                            json.dumps(request_results),
                        )
                        return {
                            "status": "Sourcing_Failed",
                            "error": f"Sourcing failed: {sup_res.error_message}",
                            "supplier_request_count": len(request_results),
                            "supplier_requests": request_results,
                            "escalation": sup_res.escalation_triggered
                        }

                    # Select best supplier quote (lowest price, already sorted in agent)
                    best_quote = sup_res.data["supplier_quotes"][0]
                    allocated_sources[item.id] = {
                        "source": "Supplier",
                        "unit_cost": best_quote["unit_cost"],
                        "details": best_quote,
                        "certificate_type": best_quote["certificate_type"],
                        "has_full_trace": True
                    }

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
                        },
                        "certificate_type": inv_data.get("certificate_type", "None"),
                        "has_full_trace":   inv_data.get("has_full_trace", True),
                    }
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
            
            for item in items:
                source_details = allocated_sources.get(item.id, {})
                comp_res = await self.compliance_agent.execute({
                    "part_number": item.resolved_part_number,
                    "source": source_details.get("source"),
                    "supplier_name": source_details.get("details", {}).get("supplier_name", "Winged Tycoons Internal"),
                    "certificate_type": source_details.get("certificate_type"),
                    "has_full_trace": source_details.get("has_full_trace", True)
                    ,"requested_certificate_type": self._requested_certification(rfq.raw_text)
                    ,"requested_condition": item.condition_preference
                    ,"condition": source_details.get("details", {}).get("condition") or item.condition_preference
                })
                
                source_details["compliance_status"] = comp_res.data.get("compliance_status", "Pass")
                
                if not comp_res.success:
                    db_service.update_rfq_status(rfq_id, "Compliance_Blocked")
                    db_service.add_audit_log(
                        rfq_id, "ComplianceAgent", "compliance_audit",
                        f"Compliance check failed for '{item.resolved_part_number}': {comp_res.error_message}",
                        "FAILURE", json.dumps(comp_res.dict())
                    )
                    return {
                        "status": "Compliance_Blocked",
                        "error": f"Compliance Blocked: {comp_res.error_message}",
                        "escalation": comp_res.escalation_triggered
                    }
                    
                if comp_res.escalation_triggered and comp_res.escalation_triggered.condition == "missing_airworthiness_certificate":
                    # Warning requiring manual waiver
                    db_service.update_rfq_status(rfq_id, "Compliance_Warning")
                    db_service.add_audit_log(
                        rfq_id, "ComplianceAgent", "compliance_audit",
                        f"Compliance warning: {', '.join(comp_res.data.get('issues_detected', []))}",
                        "WARNING", json.dumps(comp_res.dict())
                    )
                    return {
                        "status": "Compliance_Warning",
                        "error": "Missing trace/compliance certifications. Human operator review is mandatory.",
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
            
            has_low_margin_escalation = False
            margin_esc_rule = None
            
            for item in items:
                source_details = allocated_sources.get(item.id, {})
                price_res = await self.pricing_agent.execute({
                    "unit_cost": source_details.get("unit_cost", 0.0),
                    "quantity": item.quantity,
                    "urgency": "Routine",
                    "source": source_details.get("source")
                })
                
                p_data = price_res.data
                
                # Check low-margin warning
                if price_res.escalation_triggered and price_res.escalation_triggered.condition == "margin_below_threshold":
                    has_low_margin_escalation = True
                    margin_esc_rule = price_res.escalation_triggered
                    db_service.add_audit_log(
                        rfq_id, "PricingAgent", "pricing_calc",
                        f"Low margin warning on item '{item.resolved_part_number}': Margin is {p_data.get('margin_percent')}% (below 10%).",
                        "WARNING", json.dumps(price_res.dict())
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
                    "attachments": getattr(item, "attachments", [])
                })
                
            # Generate actual Quote structures
            rfq = db_service.update_rfq_status(rfq_id, "Quote_Generation")
            
            # Save state context to proceed to Quote Gen
            context = {
                "quote_items_draft": quote_items_draft,
                "shipping_total": 0.0,
                "has_low_margin_escalation": has_low_margin_escalation,
                "margin_esc_rule": margin_esc_rule
            }
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
                )
                
            # Log success
            db_service.add_audit_log(
                rfq_id, "QuoteGenerationAgent", "quote_assembly",
                f"Generated formal Quote draft '{quote.id}' with total value ${quote.total_amount:.2f}.",
                "SUCCESS", json.dumps(q_data)
            )
            
            # Customer quote dispatch is autonomous. Human review begins only when a PO arrives.
            db_service.update_quote_status(quote.id, "Sent")
            db_service.update_rfq_status(rfq_id, "Quote_Sent")
            communication_result = await self._dispatch_customer_quote(rfq, quote)
            if not communication_result.success:
                db_service.update_rfq_status(rfq_id, "Quote_Dispatch_Failed")
                return {
                    "status": "Quote_Dispatch_Failed",
                    "quote_id": quote.id,
                    "error": communication_result.error_message,
                }

            status = "Quote_Sent"
            if context["has_low_margin_escalation"]:
                db_service.add_audit_log(
                    rfq_id, "PricingAgent", "low_margin_autonomous_dispatch",
                    "Quote dispatched autonomously despite low-margin escalation; PO review remains human-gated.",
                    "WARNING", json.dumps(context["margin_esc_rule"]),
                )
            db_service.add_audit_log(
                rfq_id, "CustomerCommunicationAgent", "email_dispatch",
                f"Autonomous quote email dispatched to customer '{rfq.customer_name}'.",
                "SUCCESS", json.dumps(communication_result.data),
            )
            return {"status": status, "quote_id": quote.id, "email_body": communication_result.data.get("formatted_body")}

    async def _dispatch_customer_quote(self, rfq: Any, quote: Any) -> AgentResponse:
        quote_items = db_service.get_quote_items(quote.id)
        # PartsBase's message belongs to PartsBase, not the embedded requester.
        # Send a new message to the embedded customer instead of Graph-replying
        # to the PartsBase source message.
        reply_to = None if _is_partsbase_rfq(rfq) else rfq.thread_id
        return await self.comm_agent.execute({
            "customer_email": rfq.customer_email,
            "customer_name": rfq.customer_name,
            "quote_details": {
                "quote_id": quote.id,
                "subtotal": quote.subtotal,
                "shipping_cost": quote.shipping_cost,
                "total_amount": quote.total_amount,
                "quantity_defaulted": any(
                    item.quantity == 1 and not re.search(
                        r"(?:qty|quantity|q(?:t)?y\.?)\s*[:#]?\s*\d+|\b\d+\s*(?:ea|each|pcs?|pieces?|units?)\b|\b(?:need|require|want|request|order)\s+\d+",
                        rfq.raw_text,
                        re.IGNORECASE,
                    )
                    for item in quote_items
                ),
                "items": [
                    {
                        "part_number": item.part_number,
                        "quantity": item.quantity,
                        "uom": getattr(item, "uom", "EA"),
                        "unit_price": item.unit_price,
                        "attachments": getattr(item, "attachments", []),
                    }
                    for item in quote_items
                ],
            },
            "reply_to": reply_to,
        })

    async def approve_and_send_quote(self, quote_id: str, operator_name: str, overrides: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Processes human approval. Overrides prices if supplied, recalculates totals,
        and fires Customer Communication transmission.
        """
        quote = db_service.get_quote(quote_id)
        if not quote:
            return {"error": f"Quote {quote_id} not found."}
            
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
            
        db_service.update_quote_status(quote_id, "Approved", approved_by=operator_name)
        db_service.update_rfq_status(rfq_id, "Quote_Sent")
        db_service.add_audit_log(
            rfq_id, "Orchestrator", "human_approval",
            f"Quote {quote_id} approved by commercial operator '{operator_name}'.",
            "SUCCESS"
        )
        
        # Trigger outbound email via CustomerCommunicationAgent
        rfq = db_service.get_rfq(rfq_id)
        quote_items = db_service.get_quote_items(quote_id)
        comm_res = await self.comm_agent.execute({
            "customer_email": rfq.customer_email,
            "customer_name": rfq.customer_name,
            "quote_details": {
                "quote_id": quote_id,
                "subtotal": quote.subtotal,
                "shipping_cost": quote.shipping_cost,
                "total_amount": quote.total_amount,
                "items": [
                    {
                        "part_number": item.part_number,
                        "quantity": item.quantity,
                        "uom": getattr(item, "uom", "EA"),
                        "unit_price": item.unit_price,
                        "attachments": getattr(item, "attachments", []),
                    }
                    for item in quote_items
                ],
            },
            "reply_to": rfq.thread_id,
        })
        
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
