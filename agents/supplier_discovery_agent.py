from typing import Dict, Any, List, Optional
from agents.base_agent import BaseAgent, AgentMetadata, AgentResponse, EscalationRule
from services.supplier_database import supplier_db
from services.agents.prompts import SUPPLIER_COMMUNICATION_PROMPT


class SupplierDiscoveryAgent(BaseAgent):
    """Agent responsible for matching RFQ parts to real supplier offers stored in SQLite.

    This version uses persistent supplier records rather than hard-coded mock supplier
    rankings. The agent filters offers by part_number, quantity, approval status, and
    certificate quality, then ranks by cost and lead time.
    """

    def __init__(self):
        metadata = AgentMetadata(
            name="SupplierDiscoveryAgent",
            role="Strategic Supplier Sourcing Agent",
            objective="Query mock supplier networks to source parts and obtain pricing, availability, and certification details.",
            system_instruction=SUPPLIER_COMMUNICATION_PROMPT,
            input_schema={
                "type": "object",
                "properties": {
                    "part_number": {"type": "string", "description": "Part number to source"},
                    "quantity_needed": {"type": "integer", "description": "Remaining quantity required"}
                },
                "required": ["part_number", "quantity_needed"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "sourcing_successful": {"type": "boolean"},
                    "supplier_quotes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "supplier_id": {"type": "string"},
                                "supplier_name": {"type": "string"},
                                "part_number": {"type": "string"},
                                "unit_cost": {"type": "number"},
                                "quantity_available": {"type": "integer"},
                                "lead_time_days": {"type": "integer"},
                                "certificate_type": {"type": "string"},
                                "approval_status": {"type": "string"},
                                "reliability_score": {"type": "number"},
                                "score": {"type": "number"}
                            },
                            "required": [
                                "supplier_id",
                                "supplier_name",
                                "part_number",
                                "unit_cost",
                                "quantity_available",
                                "lead_time_days",
                                "certificate_type",
                                "approval_status",
                                "reliability_score",
                                "score"
                            ]
                        }
                    }
                },
                "required": ["sourcing_successful", "supplier_quotes"]
            },
            available_tools=["supplier_network_search"],
            permissions=["query_suppliers"],
            escalation_rules=[
                EscalationRule(
                    condition="no_suppliers_found",
                    action="halt_for_review",
                    escalate_to="human_operator"
                )
            ],
            prompt_templates={
                "default": "You search external supplier databases when parts are out of stock. Collect prices, quantity, lead times, and certification information. If no suppliers have the part, escalate to human review.",
                "supplier_search": "Find the best available suppliers for the requested part and rank offers by cost, lead time, and certificate quality.",
            }
        )
        super().__init__(metadata)
        self._event_quotes: Dict[str, List[Dict[str, Any]]] = {}

    REQUIRED_TRACE_CERTIFICATES = {"FAA 8130-3", "EASA Form 1", "FAA_8130_3", "EASA_FORM_1"}

    def select_vendor(self, quotes: List[Dict[str, Any]], max_lead_time_days: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Filter unsafe offers and rank remaining vendors by 60/20/20 score."""
        eligible = [
            quote for quote in quotes
            if quote.get("certificate_type") in self.REQUIRED_TRACE_CERTIFICATES
            and int(quote.get("quantity_available", 0)) > 0
            and (max_lead_time_days is None or int(quote.get("lead_time_days", 0)) <= max_lead_time_days)
        ]
        if not eligible:
            return None

        costs = [float(quote["unit_cost"]) for quote in eligible]
        leads = [float(quote["lead_time_days"]) for quote in eligible]
        ratings = [float(quote.get("vendor_rating", quote.get("reliability_score", 0))) for quote in eligible]

        def normalized(value: float, values: List[float], inverse: bool = False) -> float:
            low, high = min(values), max(values)
            if high == low:
                return 1.0
            score = (value - low) / (high - low)
            return 1.0 - score if inverse else score

        ranked = []
        for quote in eligible:
            score = (
                0.60 * normalized(float(quote["unit_cost"]), costs, inverse=True)
                + 0.20 * normalized(float(quote["lead_time_days"]), leads, inverse=True)
                + 0.20 * normalized(float(quote.get("vendor_rating", quote.get("reliability_score", 0))), ratings)
            )
            ranked.append({**quote, "weighted_score": round(score, 6)})
        return max(ranked, key=lambda quote: quote["weighted_score"])

    async def handle_supplier_rfq_broadcast(self, event: Any) -> None:
        self._event_quotes[event.correlation_id] = []

    async def handle_supplier_quote_received(self, event: Any) -> Optional[Dict[str, Any]]:
        quotes = self._event_quotes.setdefault(event.correlation_id, [])
        quotes.append(dict(event.payload))
        expected = int(event.payload.get("expected_supplier_count", 0))
        if expected and len(quotes) < expected:
            return None
        selected = self.select_vendor(quotes, event.payload.get("max_lead_time_days"))
        return selected

    async def execute(self, inputs: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        """Entry point called by the orchestrator.

        Delegates to :meth:`search_suppliers` and formats the result as an
        ``AgentResponse``.
        """
        part_number = inputs.get("part_number", "").strip().upper()
        qty_needed = inputs.get("quantity_needed", 1)

        results = self.search_suppliers(part_number, qty_needed)
        if not results:
            return AgentResponse(
                success=False,
                error_message=f"No suppliers found offering part number '{part_number}'.",
                escalation_triggered=self.metadata.escalation_rules[0]
            )

        return AgentResponse(
            success=True,
            data={
                "sourcing_successful": True,
                "supplier_quotes": results
            }
        )

    def search_suppliers(self, part_number: str, quantity: int) -> List[Dict[str, Any]]:
        """Return the top supplier offers stored in SQLite for a part number."""
        if not part_number:
            return []

        records = supplier_db.find_supplier_offers(part_number, quantity_needed=quantity)
        ranked: List[Dict[str, Any]] = []

        for record in records:
            unit_cost = float(record.get("unit_cost") or 0.0)
            lead_time = int(record.get("lead_time_days") or 0)
            confidence = float(record.get("confidence") or 0.0)
            valid_certificate = record.get("certificate_type") not in (None, "", "None")
            score = 0.0
            if record.get("approval_status") == "Approved":
                score += 40
            if valid_certificate:
                score += 20
            if record.get("quantity_available", 0) >= quantity:
                score += 20
            if lead_time:
                score += max(0, 15 - lead_time)
            if unit_cost:
                score += max(0, 25 - (unit_cost / 100.0))
            score += confidence * 10

            ranked.append({
                "supplier_id": record.get("supplier_id", ""),
                "supplier_name": record.get("supplier_name", "Unknown Supplier"),
                "part_number": part_number.upper(),
                "unit_cost": unit_cost,
                "quantity_available": int(record.get("quantity_available") or 0),
                "lead_time_days": lead_time,
                "certificate_type": record.get("certificate_type") or "None",
                "approval_status": record.get("approval_status") or "Pending",
                "reliability_score": round(confidence * 100, 2),
                "score": round(score, 2),
            })

        return sorted(
            ranked,
            key=lambda x: (x["unit_cost"], x["lead_time_days"], -x["reliability_score"], -x["score"]),
        )[:3]
