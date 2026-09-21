from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ConditionCode(str, Enum):
    NE = "NE"
    NS = "NS"
    OH = "OH"
    AR = "AR"


class TraceCertificate(str, Enum):
    FAA_8130_3 = "FAA_8130_3"
    EASA_FORM_1 = "EASA_FORM_1"
    OEM_TRACE = "OEM_TRACE"
    COC = "COC"


class ExtractedRFQPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rfq_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    part_number: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    condition: ConditionCode
    target_delivery_date: Optional[datetime] = None
    extraction_confidence: float = Field(ge=0.0, le=1.0)


class SourcingResultPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rfq_id: str = Field(min_length=1)
    part_number: str = Field(min_length=1)
    vendor_id: str = Field(min_length=1)
    available_qty: int = Field(ge=0)
    unit_cost_usd: float = Field(gt=0.0)
    lead_time_days: int = Field(ge=0)
    trace_certificate: TraceCertificate


class ComplianceResultPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rfq_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    is_sanctioned: bool
    match_score: float = Field(ge=0.0, le=1.0)
    export_control_flag: bool
    audit_notes: str = Field(min_length=1)


class CalculatedQuotePayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: str = Field(min_length=1)
    rfq_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    part_number: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    unit_cost_usd: float = Field(ge=0.0)
    unit_sell_usd: float = Field(gt=0.0)
    gross_margin: float = Field(ge=-1.0, le=1.0)
    total_quote_value_usd: float = Field(gt=0.0)
    expires_at: datetime


class PolicyDecisionPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    can_auto_dispatch: bool
    composite_confidence: float = Field(ge=0.0, le=1.0)
    escalation_reasons: List[str] = Field(default_factory=list)


class HumanEscalationPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_name: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    source_event_id: Optional[str] = None
