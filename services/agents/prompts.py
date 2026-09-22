"""Shared prompt and state contracts for the sales and purchasing agents."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentPipelineState(BaseModel):
    """Canonical context passed between extraction, sourcing, compliance, and communication."""

    rfq_id: str
    customer_email: str = ""
    customer_name: str = ""
    customer_tier: str = "standard"
    urgency: Literal["AOG", "Urgent", "Routine"] = "Routine"
    requested_items: list[dict[str, Any]] = Field(default_factory=list)
    inventory_matches: list[dict[str, Any]] = Field(default_factory=list)
    supplier_quotes: list[dict[str, Any]] = Field(default_factory=list)
    compliance_status: str = "PENDING"
    compliance_issues: list[str] = Field(default_factory=list)
    quote_id: str | None = None
    quote_total: float | None = None
    lead_time_days: int | None = None
    communication_status: str = "PENDING"


RFQ_INTAKE_PROMPT = (
    "Extract only facts explicitly present in the subject, body, and attachment text. "
    "Normalize part numbers, quantities, condition codes NE/OH/AR/NS, target dates, "
    "certificates, customer identity, and AOG urgency. Return the declared Pydantic JSON "
    "contract; use null or missing_fields instead of guessing."
)

SOURCING_PROMPT = (
    "Use the shared pipeline state and authoritative inventory or supplier records. "
    "Preserve requested quantities and conditions, rank offers by traceability, price, "
    "and lead time, and never expose supplier costs in customer-facing content."
)

COMPLIANCE_PROMPT = (
    "Check requested certificates, trace completeness, supplier approval, export-control "
    "signals, and condition compatibility. Return APPROVED, HUMAN_REVIEW_REQUIRED, or "
    "REJECTED with concrete issues and never silently downgrade restricted suppliers."
)

CUSTOMER_COMMUNICATION_PROMPT = (
    "Write a concise, natural, professional customer email using only approved state. "
    "Include part number, quantity, condition, certification, customer price, lead time, "
    "validity, and next step. Never include unit cost, margin, supplier identity, or internal locations."
)

SUPPLIER_COMMUNICATION_PROMPT = (
    "Write a courteous supplier request with part number, quantity, condition, certificate "
    "requirements, lead time, validity, and quantity-discount questions where relevant."
)
