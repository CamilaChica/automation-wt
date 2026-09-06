from typing import Dict, Any, Optional
from agents.base_agent import BaseAgent, AgentMetadata, AgentResponse, EscalationRule

class PricingAgent(BaseAgent):
    def __init__(self):
        metadata = AgentMetadata(
            name="PricingAgent",
            role="Commercial Pricing & Margins Analyst",
            objective="Compute retail markup, freight estimates, and total prices for RFQ items.",
            system_instructions=(
                "You calculate target margins (default 20%). Apply discount matrices for large orders. "
                "Incorporate shipping premiums for expedite priorities. If profit margin drops below the "
                "10% threshold, raise a low-margin escalation warning for commercial approval."
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
                    "calculated_markup_amount": {"type": "number"},
                    "shipping_estimate": {"type": "number"}
                },
                "required": ["unit_cost", "suggested_unit_price", "margin_percent", "shipping_estimate"]
            },
            available_tools=["margin_calculator", "shipping_estimator"],
            permissions=["calculate_prices"],
            escalation_rules=[
                EscalationRule(
                    condition="margin_below_threshold",
                    action="halt_for_review",
                    escalate_to="human_operator"
                )
            ]
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
            
        # Expedited shipping premium adjustments
        shipping_estimate = 50.00
        if urgency == "AOG":
            shipping_estimate = 250.00
            # Increase margin slightly due to rapid handling value
            default_margin += 0.02
        elif urgency == "Expedite":
            shipping_estimate = 120.00
            
        # Let's say cost is very high and we want to enforce price matches that reduce margin
        # Mocking an overridden low-margin scenario:
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
        
        response_data = {
            "unit_cost": unit_cost,
            "suggested_unit_price": suggested_unit_price,
            "margin_percent": margin_percent,
            "calculated_markup_amount": calculated_markup,
            "shipping_estimate": shipping_estimate
        }
        
        # Escalation condition: Margin < 10%
        if margin_percent < 10.0:
            return AgentResponse(
                success=True, # Calculation completed, but needs human override
                data=response_data,
                escalation_triggered=self.metadata.escalation_rules[0]
            )
            
        return AgentResponse(
            success=True,
            data=response_data
        )
