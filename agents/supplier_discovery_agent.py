from typing import Dict, Any, List, Optional
from agents.base_agent import BaseAgent, AgentMetadata, AgentResponse, EscalationRule


class SupplierDiscoveryAgent(BaseAgent):
    """Agent responsible for sourcing parts from external approved suppliers.

    It provides a ``search_suppliers`` helper that ranks suppliers based on a
    multi‑criteria score. The ranking criteria (in order of importance) are:

    1. **Availability** – can the supplier meet the required quantity?
    2. **Approval status** – is the supplier approved for our program?
    3. **Documentation** – does the supplier provide a valid airworthiness
       certificate?
    4. **Lead time** – shorter lead times are preferred.
    5. **Price** – lower unit cost is favourable but not the sole driver.
    6. **Reliability** – historical reliability score (0‑100).
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
        """Return the top three suppliers for *part_number* that can meet *quantity*.

        The function uses a mock supplier list, computes a composite score based on
        the six ranking criteria and returns the highest‑scoring candidates.
        """
        # -----------------------------------------------------------------
        # Mock supplier database – in a real system this would be a service call.
        # -----------------------------------------------------------------
        mock_suppliers: List[Dict[str, Any]] = [
            {
                "supplier_id": "SUP-001",
                "supplier_name": "Apex Aero Components",
                "part_number": part_number,
                "unit_cost": 1100.00,
                "quantity_available": 10,
                "lead_time_days": 3,
                "certificate_type": "FAA 8130-3",
                "approval_status": "Approved",
                "reliability_score": 92,
                "certification_available": True,
            },
            {
                "supplier_id": "SUP-002",
                "supplier_name": "Vanguard Spares",
                "part_number": part_number,
                "unit_cost": 1050.00,
                "quantity_available": 3,
                "lead_time_days": 7,
                "certificate_type": "FAA 8130-3",
                "approval_status": "Approved",
                "reliability_score": 88,
                "certification_available": True,
            },
            {
                "supplier_id": "SUP-003",
                "supplier_name": "Horizon MRO Parts",
                "part_number": part_number,
                "unit_cost": 500.00,
                "quantity_available": 5,
                "lead_time_days": 2,
                "certificate_type": "FAA 8130-3",
                "approval_status": "Approved",
                "reliability_score": 80,
                "certification_available": True,
            },
            {
                "supplier_id": "SUP-004",
                "supplier_name": "Suspect Supplier Corp",
                "part_number": part_number,
                "unit_cost": 300.00,
                "quantity_available": 1,
                "lead_time_days": 1,
                "certificate_type": "None",
                "approval_status": "Pending",
                "reliability_score": 60,
                "certification_available": False,
            },
        ]

        # Filter suppliers that can meet the required quantity.
        viable = [s for s in mock_suppliers if s["quantity_available"] >= quantity]
        if not viable:
            # If none can fully satisfy, keep all suppliers to still provide quotes.
            viable = mock_suppliers

        # -----------------------------------------------------------------
        # Scoring – each criterion contributes a weighted number of points.
        # -----------------------------------------------------------------
        max_price = max(s["unit_cost"] for s in viable) or 1
        max_lead = max(s["lead_time_days"] for s in viable) or 1

        for s in viable:
            # Availability – up to 20 points.
            avail_score = 20 * min(1.0, s["quantity_available"] / quantity)
            # Approval – 15 points if approved.
            approval_score = 15 if s["approval_status"] == "Approved" else 0
            # Documentation – 10 points if certificate is present.
            doc_score = 10 if s.get("certification_available", False) else 0
            # Lead time – inverse proportional, up to 15 points.
            lead_score = 15 * (max_lead - s["lead_time_days"]) / max_lead
            # Price – inverse proportional, up to 15 points.
            price_score = 15 * (max_price - s["unit_cost"]) / max_price
            # Reliability – scaled to 15 points.
            reliability_score = 15 * (s["reliability_score"] / 100)

            total = (
                avail_score
                + approval_score
                + doc_score
                + lead_score
                + price_score
                + reliability_score
            )
            s["score"] = round(total, 2)

        # Sort by descending score and keep top three.
        ranked = sorted(viable, key=lambda x: x["score"], reverse=True)[:3]

        # Return a clean list of dicts with the required fields.
        return [
            {
                "supplier_id": r["supplier_id"],
                "supplier_name": r["supplier_name"],
                "part_number": r["part_number"],
                "unit_cost": r["unit_cost"],
                "quantity_available": r["quantity_available"],
                "lead_time_days": r["lead_time_days"],
                "certificate_type": r["certificate_type"],
                "approval_status": r["approval_status"],
                "reliability_score": r["reliability_score"],
                "score": r["score"],
            }
            for r in ranked
        ]
