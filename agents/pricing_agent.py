from typing import Dict, Any, Optional
from agents.base_agent import BaseAgent, AgentMetadata, AgentResponse, EscalationRule


class NegativeMarginError(ValueError):
    """Raised when deterministic customer pricing does not exceed source cost."""

class PricingAgent(BaseAgent):
    MIN_AUTONOMOUS_MARGIN = 0.18

    def __init__(self):
        metadata = AgentMetadata(
            name="PricingAgent",
            role="Commercial Pricing & Margins Analyst",
            objective="Compute retail markup and total prices for RFQ items without quoting shipping fees.",
            system_instruction=(
                "You calculate target margins (default 20%). Apply discount matrices for large orders. "
                "Do not add or quote shipping charges; customers choose their own carrier and account. "
                "If profit margin drops below the 10% threshold, raise a low-margin escalation warning for commercial approval."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "unit_cost": {"type": "number", "description": "Source unit cost"},
                    "quantity": {"type": "integer", "description": "Number of units"},
                    "urgency": {"type": "string", "enum": ["Routine", "Expedite", "AOG (Aircraft on Ground)"]},
                    "source": {"type": "string", "enum": ["Inventory", "Supplier"]}
                },
                "required": ["unit_cost", "quantity"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "unit_cost": {"type": "number"},
                    "suggested_unit_price": {"type": "number"},
                    "margin_percent": {"type": "number"},
                    "calculated_markup_amount": {"type": "number"}
                },
                "required": ["unit_cost", "suggested_unit_price", "margin_percent"]
            },
            available_tools=["margin_calculator"],
            permissions=["calculate_prices"],
            escalation_rules=[
                EscalationRule(
                    condition="margin_below_threshold",
                    action="halt_for_review",
                    escalate_to="human_operator"
                )
            ],
            prompt_templates={
                "default": "You calculate target margins (default 20%). Apply discount matrices for large orders. Do not add or quote shipping charges; customers choose their own carrier and account. If profit margin drops below the 10% threshold, raise a low-margin escalation warning for commercial approval.",
                "pricing_calc": "Compute the suggested unit price and confirm the margin remains above the approved threshold.",
            }
        )
        super().__init__(metadata)

    async def execute(self, inputs: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        unit_cost = inputs.get("unit_cost", 0.0)
        qty = inputs.get("quantity", 1)
        requested_limit = (context or {}).get("requested_price_limit")
        from services.orchestration_service import OrchestrationService

        try:
            response_data, low_margin = OrchestrationService.calculate_pricing(
                float(unit_cost),
                int(qty),
                float(requested_limit) if requested_limit else None,
            )
        except ValueError as exc:
            raise NegativeMarginError(str(exc)) from exc

        if low_margin:
            return AgentResponse(
                success=True,
                data=response_data,
                escalation_triggered=self.metadata.escalation_rules[0]
            )
            
        return AgentResponse(
            success=True,
            data=response_data
        )
