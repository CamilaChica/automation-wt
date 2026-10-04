from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ExtractedField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Optional[str] = None
    source_snippet: Optional[str] = None


class ResolutionHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    candidate_value: Optional[str] = None
    source_snippets: List[str] = Field(default_factory=list)


class PolicyEvaluationRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject", "review"]
    rationale: str = Field(min_length=1)
    policy_keys: List[str] = Field(default_factory=list)
    missing_evidence: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class SupplierEmailDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=5, max_length=200)
    body_text: str = Field(min_length=20)
    requested_fields: List[str] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)


class RFQExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_number: ExtractedField
    quantity: ExtractedField
    condition_code: ExtractedField
    target_price: ExtractedField
    lead_time_days: ExtractedField = Field(default_factory=ExtractedField)
    unit_of_measure: ExtractedField = Field(default_factory=ExtractedField)
    currency: ExtractedField = Field(default_factory=ExtractedField)
    missing_fields: List[str] = Field(default_factory=list)
    needs_escalation: bool = False
    escalation_reason: Optional[str] = None
    resolution_hypotheses: List[ResolutionHypothesis] = Field(default_factory=list)


class ExtractionTaskContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_id: str
    version: str
    task: Literal["rfq_extraction", "supplier_quote_extraction"]
    prompt_version: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    allowed_models: List[str]
    escalation_models: List[str] = Field(default_factory=list)
    abstention_behavior: str
    can_escalate: bool
    system_prompt: str