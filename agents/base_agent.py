from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

class EscalationRule(BaseModel):
    condition: str = Field(description="The condition that triggers the escalation")
    action: str = Field(description="The action to take when the condition is met (e.g., 'halt_for_review')")
    escalate_to: str = Field(description="Who or what system to escalate to (e.g., 'human_operator', 'orchestrator')")

class AgentMetadata(BaseModel):
    name: str = Field(description="Unique agent identifier")
    role: str = Field(description="Functional role of the agent")
    objective: str = Field(description="The core objective or goal of the agent")
    system_instructions: str = Field(description="Core prompt and guidelines guiding the agent's behavior")
    input_schema: Dict[str, Any] = Field(description="JSON schema describing the inputs this agent expects")
    output_schema: Dict[str, Any] = Field(description="JSON schema describing the outputs this agent generates")
    available_tools: List[str] = Field(description="List of tool names the agent has access to")
    permissions: List[str] = Field(description="Actions or resources this agent is permitted to access")
    escalation_rules: List[EscalationRule] = Field(description="Rules for when the agent must yield control to a human or coordinator")

class AgentResponse(BaseModel):
    success: bool = Field(description="Indicates whether the task completed successfully without escalation")
    data: Dict[str, Any] = Field(default_factory=dict, description="Structured output payload on success")
    error_message: Optional[str] = Field(None, description="Detailed error explanation if success is False")
    escalation_triggered: Optional[EscalationRule] = Field(None, description="The rule that triggered an escalation, if any")

class BaseAgent:
    def __init__(self, metadata: AgentMetadata):
        self.metadata = metadata

    async def execute(self, inputs: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        """
        Execute the agent logic.
        Each agent subclass must override this method.
        """
        raise NotImplementedError("Subclasses must implement execute")
