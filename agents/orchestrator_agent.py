from typing import Dict, Any, Optional
from agents.base_agent import BaseAgent, AgentMetadata, AgentResponse
from services.llm_tool_orchestrator import LLMToolOrchestrator, create_default_agent_tool_orchestrator

class OrchestratorAgent(BaseAgent):
    def __init__(self, tool_orchestrator: LLMToolOrchestrator | None = None):
        metadata = AgentMetadata(
            name="OrchestratorAgent",
            role="RFQ-to-Quote Multi-Agent Coordinator",
            objective="Understand internal RFQ requests, select approved agent tools, and coordinate bounded multi-step analysis.",
            system_instruction=(
                "You coordinate internal RFQ analysis by selecting only the tools explicitly provided "
                "for the current request. Use tool results to decide whether another tool is needed, "
                "then summarize only what the evidence supports. For response_mode='human', produce "
                "descriptive, clear prose; for response_mode='app', produce only the declared structured JSON. "
                "Tool calls are validated and authorized by "
                "the backend. Never bypass the production workflow state machine, compliance policy, "
                "or human approval requirements. Do not send communications, issue quotes, or mutate "
                "workflow state through this analysis interface."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "rfq_id": {"type": "string", "description": "RFQ process ID"},
                    "command": {"type": "string", "enum": ["START", "CONTINUE", "RETRY"]},
                    "query": {"type": "string", "minLength": 1, "maxLength": 4000},
                    "response_mode": {
                        "type": "string",
                        "enum": ["human", "app"],
                        "description": "Use human for descriptive prose or app for validated structured JSON.",
                    },
                },
                "anyOf": [
                    {"required": ["query"]},
                    {"required": ["rfq_id"]},
                ]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "response_mode": {"type": "string", "enum": ["human", "app"]},
                    "next_step": {"type": "string"},
                    "is_complete": {"type": "boolean"},
                    "needs_approval": {"type": "boolean"},
                    "log_message": {"type": "string"},
                    "structured_output": {
                        "type": "object",
                        "properties": {
                            "status": {
                                "type": "string",
                                "enum": ["complete", "partial", "insufficient_evidence"],
                            },
                            "summary": {"type": "string"},
                            "findings": {"type": "array", "items": {"type": "object"}},
                            "missing_information": {"type": "array", "items": {"type": "string"}},
                            "next_steps": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": [
                            "status",
                            "summary",
                            "findings",
                            "missing_information",
                            "next_steps",
                        ],
                        "additionalProperties": False,
                    },
                    "tool_calls": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool_name": {"type": "string"},
                                "arguments": {"type": "object"},
                                "result": {"type": "object"},
                            },
                            "required": ["tool_name", "arguments", "result"],
                            "additionalProperties": False,
                        },
                    },
                    "tool_limit_reached": {"type": "boolean"},
                },
                "required": [
                    "response_mode",
                    "next_step",
                    "is_complete",
                    "needs_approval",
                    "tool_calls",
                    "tool_limit_reached",
                ],
                "oneOf": [
                    {"required": ["log_message"]},
                    {"required": ["structured_output"]},
                ],
            },
            available_tools=[
                "lookup_part",
                "check_inventory",
                "search_suppliers",
                "calculate_price",
                "query_rfq",
                "query_supplier_offers",
                "search_knowledge",
            ],
            permissions=[
                "read_catalog",
                "read_inventory",
                "query_suppliers",
                "calculate_prices",
                "read_business_records",
                "search_knowledge",
            ],
            escalation_rules=[],
            prompt_templates={
                "default": "Understand the request, choose authorized analysis tools as needed, and return a descriptive human answer or validated app JSON according to response_mode.",
                "route_workflow": "Coordinate bounded, policy-compliant analysis; the application state machine remains authoritative for production workflow transitions.",
            }
        )
        super().__init__(metadata)
        self.tool_orchestrator = tool_orchestrator or create_default_agent_tool_orchestrator()

    async def execute(self, inputs: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        rfq_id = inputs.get("rfq_id", "")
        command = inputs.get("command", "START")
        query = str(inputs.get("query") or "").strip()
        if query:
            response_mode = inputs.get("response_mode", "app")
            if response_mode not in {"human", "app"}:
                return AgentResponse(success=False, error_message="response_mode must be 'human' or 'app'.")
            auth_context = context or {}
            role = str(auth_context.get("role") or "")
            permissions = auth_context.get("permissions") or set()
            if not role:
                return AgentResponse(success=False, error_message="An authenticated role is required.")
            try:
                result = await self.tool_orchestrator.run(
                    query,
                    role=role,
                    permissions=set(permissions),
                    human_confirmed=bool(auth_context.get("human_confirmed", False)),
                    response_mode=response_mode,
                )
            except PermissionError as error:
                return AgentResponse(success=False, error_message=str(error))
            data = {
                "response_mode": response_mode,
                "next_step": "CONTINUE" if result.stopped_at_step_limit else "COMPLETED",
                "is_complete": not result.stopped_at_step_limit,
                "needs_approval": False,
                "tool_calls": [step.model_dump(mode="json") for step in result.steps],
                "tool_limit_reached": result.stopped_at_step_limit,
            }
            if response_mode == "human":
                data["log_message"] = result.answer or ""
            elif result.structured_output is not None:
                data["structured_output"] = result.structured_output.model_dump(mode="json")
            else:
                return AgentResponse(
                    success=False,
                    error_message="A validated structured orchestration result was not produced.",
                )
            return AgentResponse(success=True, data=data)

        # Preserve the existing state-machine handoff contract for pipeline callers.
        return AgentResponse(
            success=True,
            data={
                "next_step": "VALIDATING",
                "is_complete": False,
                "needs_approval": False,
                "log_message": f"Orchestration initiated for RFQ {rfq_id} with command {command}."
            }
        )
