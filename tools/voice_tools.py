from pydantic import BaseModel, ConfigDict, Field

from tools.registry import ToolDefinition, ToolRegistry


class VoiceToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InventoryLookupArguments(VoiceToolArguments):
    part_number: str = Field(min_length=1, max_length=80, description="Aircraft part number or partial part number")


class OrderStatusArguments(VoiceToolArguments):
    rfq_or_order_id: str = Field(min_length=1, max_length=100, description="RFQ or order identifier")


class CustomerConcernArguments(VoiceToolArguments):
    issue_type: str = Field(min_length=1, max_length=80)
    details: str = Field(min_length=1, max_length=2000)
    part_number: str = Field(min_length=1, max_length=80)


VOICE_TOOL_ROLES = frozenset({
    "ROLE_CUSTOMER",
    "ROLE_INTERNAL",
    "ROLE_ADMIN",
    "ROLE_MANAGER",
    "ROLE_SALES",
    "ROLE_PURCHASING",
})

VOICE_TOOL_REGISTRY = ToolRegistry([
    ToolDefinition(
        name="check_inventory_availability",
        description="Search live aerospace inventory by exact or partial part number. Quote only returned availability, condition, and trace details.",
        arguments_model=InventoryLookupArguments,
        allowed_roles=VOICE_TOOL_ROLES,
    ),
    ToolDefinition(
        name="get_order_status",
        description="Look up the current status or operator review notice for an RFQ or order. Customer access is limited to their own records.",
        arguments_model=OrderStatusArguments,
        allowed_roles=VOICE_TOOL_ROLES,
    ),
    ToolDefinition(
        name="log_customer_concern",
        description="Record a concern for operator follow-up. An authenticated user must explicitly confirm this action in the application.",
        arguments_model=CustomerConcernArguments,
        allowed_roles=VOICE_TOOL_ROLES,
        requires_confirmation=True,
    ),
])
