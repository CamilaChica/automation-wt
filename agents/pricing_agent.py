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
        urgency = inputs.get("urgency", "Routine")
        source = inputs.get("source", "Inventory")
        
        # Determine base markup margin
        default_margin = 0.20 # 20%
        
        # Apply quantity discounts
        if qty >= 10:
            default_margin = 0.15 # 15% margin
        elif qty >= 5:
            default_margin = 0.18 # 18% margin
            
        # Shipping is customer-selected and must not be embedded into the customer quote price.
        actual_margin = default_margin
        if context and context.get("requested_price_limit", 0) > 0:
            limit = context["requested_price_limit"]
            # Force target price that might dip margin
            suggested_unit_price = limit
            actual_margin = (suggested_unit_price - unit_cost) / suggested_unit_price
        else:
            # Standard calculation: Price = Cost / (1 - Margin)
            suggested_unit_price = round(unit_cost / (1 - actual_margin), 2)
            
        calculated_markup = round(suggested_unit_price - unit_cost, 2)
        margin_percent = round(actual_margin * 100, 2)

        if suggested_unit_price <= unit_cost:
            raise NegativeMarginError(
                f"Customer price ${suggested_unit_price:.2f} must exceed source cost ${unit_cost:.2f}."
            )
        
        response_data = {
            "unit_cost": unit_cost,
            "suggested_unit_price": suggested_unit_price,
            "margin_percent": margin_percent,
            "calculated_markup_amount": calculated_markup,
        }
        
        # Keep agent escalation aligned with the autonomous policy gate.
        if actual_margin < self.MIN_AUTONOMOUS_MARGIN:
            return AgentResponse(
                success=True, # Calculation completed, but needs human override
                data=response_data,
                escalation_triggered=self.metadata.escalation_rules[0]
            )
            
        return AgentResponse(
            success=True,
            data=response_data
        )
