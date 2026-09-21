from typing import Annotated, Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class QuotePayload(BaseModel):
    """Normalized policy inputs for an automatically dispatched quote."""

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        allow_inf_nan=False,
    )

    extraction_confidence: float = Field(
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices("extraction_confidence", "confidence"),
    )
    confidence_metrics: Dict[str, Annotated[float, Field(ge=0.0, le=1.0)]] = Field(default_factory=dict)
    gross_margin: float = Field(
        ge=-1.0,
        le=1.0,
        validation_alias=AliasChoices("gross_margin", "margin"),
    )
    total_amount: float = Field(
        ge=0.0,
        validation_alias=AliasChoices("total_amount", "quote_value", "total_value"),
    )
    compliance_status: str
    sanctions_hits: List[str] = Field(default_factory=list)
    sanctions_clear: Optional[bool] = None
    compliance_checks: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("compliance_status")
    @classmethod
    def normalize_compliance_status(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("compliance_status cannot be blank")
        return normalized

    @field_validator("sanctions_hits")
    @classmethod
    def normalize_sanctions_hits(cls, value: List[str]) -> List[str]:
        return [hit.strip() for hit in value if hit.strip()]


class PolicyDecision(BaseModel):
    can_auto_dispatch: bool
    escalation_reasons: List[str] = Field(default_factory=list)


class AutonomousPolicyGate:
    def __init__(
        self,
        min_extraction_confidence: float = 0.92,
        min_gross_margin: float = 0.18,
        max_auto_approve_value: float = 25000.00,
        strict_zero_sanctions: bool = True,
    ) -> None:
        if not 0.0 <= min_extraction_confidence <= 1.0:
            raise ValueError("min_extraction_confidence must be between 0 and 1")
        if min_gross_margin < 0.0:
            raise ValueError("min_gross_margin cannot be negative")
        if max_auto_approve_value < 0.0:
            raise ValueError("max_auto_approve_value cannot be negative")

        self.min_extraction_confidence = min_extraction_confidence
        self.min_gross_margin = min_gross_margin
        self.max_auto_approve_value = max_auto_approve_value
        self.strict_zero_sanctions = strict_zero_sanctions

    def evaluate_auto_dispatch(self, quote_payload: QuotePayload) -> PolicyDecision:
        if not isinstance(quote_payload, QuotePayload):
            quote_payload = QuotePayload.model_validate(quote_payload)

        reasons: List[str] = []
        if quote_payload.extraction_confidence < self.min_extraction_confidence:
            reasons.append(
                f"extraction confidence {quote_payload.extraction_confidence:.2f} "
                f"is below {self.min_extraction_confidence:.2f}"
            )
        low_confidence_metrics = [
            name for name, value in quote_payload.confidence_metrics.items()
            if value < self.min_extraction_confidence
        ]
        if low_confidence_metrics:
            reasons.append(
                f"confidence metrics below threshold: {', '.join(low_confidence_metrics)}"
            )
        if quote_payload.gross_margin < self.min_gross_margin:
            reasons.append(
                f"gross margin {quote_payload.gross_margin:.2%} "
                f"is below {self.min_gross_margin:.2%}"
            )
        if quote_payload.total_amount > self.max_auto_approve_value:
            reasons.append(
                f"quote value ${quote_payload.total_amount:,.2f} exceeds "
                f"${self.max_auto_approve_value:,.2f}"
            )

        compliance_status = quote_payload.compliance_status.strip().upper()
        if compliance_status not in {"APPROVED", "PASS", "PASSED", "CLEAR"}:
            reasons.append(f"compliance status is {quote_payload.compliance_status}")

        sanctions_present = bool(quote_payload.sanctions_hits)
        if quote_payload.sanctions_clear is False:
            sanctions_present = True
        if self.strict_zero_sanctions and sanctions_present:
            reasons.append("sanctions or denied-party matches are present")
        elif quote_payload.sanctions_clear is not True and self.strict_zero_sanctions:
            reasons.append("sanctions screening is not explicitly clear")

        failed_checks = [
            name for name, result in quote_payload.compliance_checks.items()
            if result is False or str(result).upper() in {"FAIL", "FAILED", "REJECTED"}
        ]
        if failed_checks:
            reasons.append(f"failed compliance checks: {', '.join(failed_checks)}")

        return PolicyDecision(can_auto_dispatch=not reasons, escalation_reasons=reasons)