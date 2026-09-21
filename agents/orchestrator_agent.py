from typing import Dict, Any, Optional
from agents.base_agent import BaseAgent, AgentMetadata, AgentResponse

class OrchestratorAgent(BaseAgent):
    def __init__(self):
        metadata = AgentMetadata(
            name="OrchestratorAgent",
            role="RFQ-to-Quote Multi-Agent Coordinator",
            objective="Coordinate state machine execution, route tasks to worker agents, and log progress.",
            system_instruction=(
                "You manage the RFQ processing pipeline. Sequentially run the Intake, Catalog Validation, "
                "Inventory Lookups, Sourcing, Compliance, Pricing, and Quote Generation stages. "
                "Write step results into audit logs. Halt when manual reviews or overrides are triggered."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "rfq_id": {"type": "string", "description": "RFQ process ID"},
                    "command": {"type": "string", "enum": ["START", "CONTINUE", "RETRY"]}
                },
                "required": ["rfq_id"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "next_step": {"type": "string"},
                    "is_complete": {"type": "boolean"},
                    "needs_approval": {"type": "boolean"},
                    "log_message": {"type": "string"}
                },
                "required": ["next_step", "is_complete", "needs_approval"]
            },
            available_tools=["database_access", "state_router"],
            permissions=["manage_workflow", "write_logs"],
            escalation_rules=[],
            prompt_templates={
                "default": "You manage the RFQ processing pipeline. Sequentially run the Intake, Catalog Validation, Inventory Lookups, Sourcing, Compliance, Pricing, and Quote Generation stages. Write step results into audit logs. Halt when manual reviews or overrides are triggered.",
                "route_workflow": "Advance the RFQ through the approved workflow and coordinate any required escalation.",
            }
        )
        super().__init__(metadata)

    async def execute(self, inputs: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        # The orchestrator uses DB services to fetch state and execute stages
        # A concrete implementation of the coordination logic will run in services/orchestration_service.py
        # Here we define the standard orchestrator interface and state router
        rfq_id = inputs.get("rfq_id", "")
        command = inputs.get("command", "START")
        
        # Returns coordinates to state routing
        return AgentResponse(
            success=True,
            data={
                "next_step": "VALIDATING",
                "is_complete": False,
                "needs_approval": False,
                "log_message": f"Orchestration initiated for RFQ {rfq_id} with command {command}."
            }
        )
