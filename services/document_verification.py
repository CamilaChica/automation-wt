"""Validated aviation document extraction and deterministic discrepancy checks."""

from __future__ import annotations

from enum import StrEnum
from typing import List

from pydantic import BaseModel, ConfigDict, Field


class DocumentType(StrEnum):
    FAA_8130_3 = "FAA_8130-3"
    EASA_FORM_1 = "EASA_FORM_1"
    CERTIFICATE_OF_CONFORMITY = "CERTIFICATE_OF_CONFORMITY"
    UNKNOWN = "UNKNOWN"


class ExtractedCertificate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: DocumentType
    part_number: str = Field(..., min_length=1)
    serial_number: str | None = None
    condition_code: str | None = None
    certificate_number: str | None = None
    repair_station_number: str | None = None
    work_order_number: str | None = None
    issue_date: str | None = None
    confidence: float = Field(..., ge=0, le=1)


class DocumentVerificationRequest(BaseModel):
    expected_part_number: str = Field(..., min_length=1)
    expected_serial_number: str | None = None
    expected_condition_code: str | None = None
    minimum_confidence: float = Field(0.85, ge=0, le=1)
    extracted: ExtractedCertificate


class DocumentVerificationResult(BaseModel):
    status: str
    discrepancies: List[str] = Field(default_factory=list)
    requires_human_review: bool
    summary: str


def verify_certificate(request: DocumentVerificationRequest) -> DocumentVerificationResult:
    extracted = request.extracted
    discrepancies: List[str] = []
    if extracted.part_number.strip().upper() != request.expected_part_number.strip().upper():
        discrepancies.append("Part number does not match the expected RFQ or purchase-order part number.")
    if request.expected_serial_number and extracted.serial_number != request.expected_serial_number:
        discrepancies.append("Serial number does not match the expected serialized item.")
    if request.expected_condition_code and extracted.condition_code:
        if extracted.condition_code.strip().upper() != request.expected_condition_code.strip().upper():
            discrepancies.append("Condition code does not match the requested condition.")
    if extracted.confidence < request.minimum_confidence:
        discrepancies.append("Document extraction confidence is below the required threshold.")

    if discrepancies:
        status = "REVIEW_REQUIRED"
        summary = "Certificate verification requires human review before fulfillment."
    else:
        status = "VERIFIED"
        summary = "Certificate fields match the expected part and confidence threshold."
    return DocumentVerificationResult(
        status=status,
        discrepancies=discrepancies,
        requires_human_review=bool(discrepancies),
        summary=summary,
    )
