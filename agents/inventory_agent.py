from typing import Dict, Any, Optional
from agents.base_agent import BaseAgent, AgentMetadata, AgentResponse, EscalationRule
from tools.tool_interfaces import CheckInventoryTool


class InventoryAgent(BaseAgent):
    """
    InventoryAgent — Warehouse Stock Controller
    -------------------------------------------
    Queries persisted warehouse inventory for a requested part number and
    quantity, then classifies the recorded available quantity.

    Core calculation
    ~~~~~~~~~~~~~~~~
        available_to_promise = persisted quantity_available

    Response contract
    ~~~~~~~~~~~~~~~~~
        requested_quantity   – quantity asked for
        available_quantity   – ATP computed from live stock records
        shortage_quantity    – max(0, requested - available)
        condition            – airworthiness condition code (NE, NS, OH, AR)
        warehouse            – warehouse identifier
        lead_time            – estimated shipping readiness lead time
        availability_status  – IN_STOCK | PARTIAL_OR_SHORTAGE | NOT_FOUND

    Inventory integrity rule
    ~~~~~~~~~~~~~~~~~~~~~~~~
        The agent NEVER invents inventory.  If a part is not found in the
        database the response reflects zero availability and NOT_FOUND status.
        If stock exists but is insufficient, availability_status is set to
        PARTIAL_OR_SHORTAGE and an escalation is triggered to route the
        shortage to external sourcing.
    """

    def __init__(self):
        metadata = AgentMetadata(
            name="InventoryAgent",
            role="Inventory Stock Controller",
            objective=(
                "Query and report physical warehouse stock against RFQ item demands "
                "using Available-To-Promise (ATP) logic. Never fabricate inventory."
            ),
            system_instruction=(
                "You query the internal warehouse database via the check_inventory tool. "
                "Use the persisted quantity_available value. Do not infer reservation counts. "
                "If available quantity >= requested quantity → IN_STOCK. "
                "If available quantity < requested quantity → PARTIAL_OR_SHORTAGE, escalate to sourcing. "
                "If part is unknown → NOT_FOUND, escalate to sourcing. "
                "Do NOT guess or invent quantities. Only report what is physically recorded."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "part_number": {
                        "type": "string",
                        "description": "Resolved canonical part number to look up"
                    },
                    "requested_quantity": {
                        "type": "integer",
                        "description": "Number of units requested by the customer"
                    }
                },
                "required": ["part_number", "requested_quantity"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "requested_quantity":  {"type": "integer"},
                    "available_quantity":  {"type": "integer",
                                           "description": "Quantity available in persisted inventory records"},
                    "shortage_quantity":   {"type": "integer"},
                    "condition":           {"type": "string"},
                    "warehouse":           {"type": "string"},
                    "lead_time":           {"type": "string"},
                    "availability_status": {
                        "type": "string",
                        "enum": ["IN_STOCK", "PARTIAL_OR_SHORTAGE", "NOT_FOUND"]
                    },
                    # Extended fields consumed by ComplianceAgent and PricingAgent
                    "unit_cost":           {"type": "number"},
                    "certificate_type":    {"type": "string"},
                    "has_full_trace":      {"type": "boolean"},
                },
                "required": [
                    "requested_quantity", "available_quantity", "shortage_quantity",
                    "condition", "warehouse", "lead_time", "availability_status"
                ]
            },
            available_tools=["check_inventory"],
            permissions=["read_inventory"],
            escalation_rules=[
                EscalationRule(
                    condition="stockout_detected",
                    action="route_to_sourcing",
                    escalate_to="orchestrator"
                )
            ],
            prompt_templates={
                "default": "Query persisted warehouse inventory via check_inventory and use its recorded available quantity. If enough is available -> IN_STOCK. If insufficient -> PARTIAL_OR_SHORTAGE and escalate to sourcing. If the part is unknown -> NOT_FOUND and escalate. Do not infer reservations or invent quantities.",
                "stock_check": "Validate the available inventory quantity and determine ATP before continuing with pricing.",
            }
        )
        super().__init__(metadata)
        # Instantiate the tool directly (no LLM tool-call layer in this MVP)
        self._check_inventory_tool = CheckInventoryTool()

    # ------------------------------------------------------------------
    # Main execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        inputs: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> AgentResponse:
        part_number: str = inputs.get("part_number", "").strip().upper()
        requested_qty: int = max(1, int(inputs.get("requested_quantity", 1)))

        # ── Step 1: Call the check_inventory tool ──────────────────────
        tool_result: Dict[str, Any] = await self._check_inventory_tool.run({
            "part_number": part_number,
            "quantity": requested_qty
        })

        # ── Step 2: Extract standardised fields ────────────────────────
        available_qty:       int  = tool_result["available_quantity"]
        shortage_qty:        int  = tool_result["shortage_quantity"]
        availability_status: str  = tool_result["availability_status"]
        condition:           str  = tool_result["condition"]
        warehouse:           str  = tool_result["warehouse"]
        lead_time:           str  = tool_result["lead_time"]

        # Pipeline-compatibility fields (used by Compliance & Pricing agents)
        unit_cost:        float = tool_result.get("unit_cost", 0.0)
        certificate_type: str   = tool_result.get("certificate_type", "None")
        has_full_trace:   bool  = tool_result.get("has_full_trace", False)

        # ── Step 3: Build response payload ─────────────────────────────
        response_data: Dict[str, Any] = {
            "requested_quantity":  requested_qty,
            "available_quantity":  available_qty,
            "shortage_quantity":   shortage_qty,
            "condition":           condition,
            "warehouse":           warehouse,
            "lead_time":           lead_time,
            "availability_status": availability_status,
            # Extended downstream fields
            "unit_cost":           unit_cost,
            "certificate_type":    certificate_type,
            "has_full_trace":      has_full_trace,
        }

        # ── Step 4: Determine escalation ───────────────────────────────
        #
        # Escalate whenever we cannot fully fulfil the request from internal stock,
        # regardless of whether it is a partial shortage or a complete stockout /
        # unknown part.  The orchestrator will route the shortage quantity to the
        # SupplierDiscoveryAgent.
        if availability_status != "IN_STOCK":
            return AgentResponse(
                success=True,           # Tool call itself succeeded; pipeline continues
                data=response_data,
                escalation_triggered=self.metadata.escalation_rules[0]  # stockout_detected
            )

        # Fully covered from internal stock — no escalation required
        return AgentResponse(
            success=True,
            data=response_data
        )
