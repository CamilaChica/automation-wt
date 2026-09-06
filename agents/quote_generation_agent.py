import uuid
from typing import Dict, Any, Optional, List
from agents.base_agent import BaseAgent, AgentMetadata, AgentResponse

class QuoteGenerationAgent(BaseAgent):
    def __init__(self):
        metadata = AgentMetadata(
            name="QuoteGenerationAgent",
            role="Quote Generation System Specialist",
            objective="Compile finalized line items, taxes, and shipping expenses into a formal sales proposal.",
            system_instructions=(
                "You verify math operations. Sum line item totals, add shipping fees, and establish "
                "quote expiration rules. Output the formatted proposal details ready for human approval sign-off."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "rfq_id": {"type": "string"},
                    "customer": {"type": "string"},
                    "quote_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "rfq_item_id": {"type": "string"},
                                "part_number": {"type": "string"},
                                "quantity": {"type": "integer"},
                                "unit_price": {"type": "number"},
                                "condition": {"type": "string"},
                                "lead_time_days": {"type": "integer"},
                                "documentation": {"type": "string"},
                                "source": {"type": "string"},
                                "certificate_type": {"type": "string"},
                                "unit_cost": {"type": "number"},
                                "margin_percent": {"type": "number"},
                                "compliance_status": {"type": "string"}
                            },
                            "required": ["part_number", "quantity", "unit_price", "condition", "lead_time_days", "documentation", "source"]
                        }
                    },
                    "shipping_cost": {"type": "number"},
                    "quote_validity_days": {"type": "integer"},
                    "terms": {"type": "string"}
                },
                "required": ["rfq_id", "customer", "quote_items", "shipping_cost", "quote_validity_days", "terms"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "quote_id": {"type": "string"},
                    "rfq_id": {"type": "string"},
                    "customer": {"type": "string"},
                    "quotation": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "part_number": {"type": "string"},
                                "quantity": {"type": "integer"},
                                "condition": {"type": "string"},
                                "unit_price": {"type": "number"},
                                "total_price": {"type": "number"},
                                "lead_time_days": {"type": "integer"},
                                "documentation": {"type": "string"}
                            },
                            "required": ["part_number", "quantity", "condition", "unit_price", "total_price", "lead_time_days", "documentation"]
                        }
                    },
                    "subtotal": {"type": "number"},
                    "shipping_cost": {"type": "number"},
                    "total_amount": {"type": "number"},
                    "quote_validity_days": {"type": "integer"},
                    "terms": {"type": "string"},
                    "status": {"type": "string", "enum": ["PENDING_HUMAN_APPROVAL", "APPROVED", "REJECTED"]},
                    "formatted_pdf_summary": {"type": "string"}
                },
                "required": ["quote_id", "rfq_id", "customer", "quotation", "subtotal", "shipping_cost", "total_amount", "quote_validity_days", "terms", "status", "formatted_pdf_summary"]
            },
            available_tools=["document_renderer"],
            permissions=["create_quotes"],
            escalation_rules=[]
        )
        super().__init__(metadata)

    async def execute(self, inputs: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        # Extract basic fields
        rfq_id = inputs.get("rfq_id", "")
        customer = inputs.get("customer", "")
        items = inputs.get("quote_items", [])
        shipping = inputs.get("shipping_cost", 0.0)
        quote_validity = inputs.get("quote_validity_days", 30)
        terms = inputs.get("terms", "Standard terms apply.")
        
        # Compute line item totals and build structured quotation list
        quotation = []
        subtotal = 0.0
        for item in items:
            total_price = round(item["quantity"] * item["unit_price"], 2)
            subtotal += total_price
            quotation.append({
                "part_number": item.get("part_number"),
                "quantity": item.get("quantity"),
                "condition": item.get("condition"),
                "unit_price": item.get("unit_price"),
                "total_price": total_price,
                "lead_time_days": item.get("lead_time_days"),
                "documentation": item.get("documentation")
            })
        subtotal = round(subtotal, 2)
        total_amount = round(subtotal + shipping, 2)
        quote_id = f"QTE-{uuid.uuid4().hex[:6].upper()}"
        status = "PENDING_HUMAN_APPROVAL"
        
        # Generate a human‑readable PDF‑style summary (no external transmission)
        pdf_summary = (
            f"=== WINGED TYCOONS SALES PROPOSAL ===\n"
            f"Quote ID: {quote_id} | RFQ Ref: {rfq_id}\n"
            f"Customer: {customer}\n"
            f"Date: 2026-08-20 | Valid for: {quote_validity} Days\n"
            f"-------------------------------------\n"
        )
        for idx, q in enumerate(quotation, 1):
            pdf_summary += (
                f"{idx}. PART: {q['part_number']} | QTY: {q['quantity']} | Cond: {q['condition']}\n"
                f"   Unit Price: ${q['unit_price']:.2f} | Line Total: ${q['total_price']:.2f}\n"
                f"   Lead Time: {q['lead_time_days']} days | Docs: {q['documentation']}\n"
            )
        pdf_summary += (
            f"-------------------------------------\n"
            f"SUBTOTAL:          ${subtotal:.2f}\n"
            f"SHIPPING/HANDLING: ${shipping:.2f}\n"
            f"TOTAL DUE (USD):   ${total_amount:.2f}\n"
            f"STATUS: {status}\n"
            f"TERMS: {terms}\n"
            f"====================================="
        )
        
        return AgentResponse(
            success=True,
            data={
                "quote_id": quote_id,
                "rfq_id": rfq_id,
                "customer": customer,
                "quotation": quotation,
                "subtotal": subtotal,
                "shipping_cost": shipping,
                "total_amount": total_amount,
                "quote_validity_days": quote_validity,
                "terms": terms,
                "status": status,
                "formatted_pdf_summary": pdf_summary
            }
        )
