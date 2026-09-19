from typing import Dict, Any, List, Optional
from agents.base_agent import BaseAgent, AgentMetadata, AgentResponse, EscalationRule
from services.supplier_database import supplier_db


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
            system_instructions=(
                "You search external supplier databases when parts are out of stock. Collect prices, quantity, lead times, and certification information. "
                "If no suppliers have the part, escalate to human review."
            ),
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
            ]
        )
        super().__init__(metadata)

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
