"""Validated aviation document extraction and deterministic discrepancy checks."""

from __future__ import annotations

from enum import StrEnum
from typing import List
import hashlib
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from services.document_parser import extract_attachment_text


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
    elif request.expected_condition_code:
        discrepancies.append("Expected condition code is missing from the document.")
    if extracted.document_type == DocumentType.UNKNOWN:
        discrepancies.append("The certificate type is not recognized.")
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


def inspect_document(attachment: dict[str, Any]) -> dict[str, Any]:
    """Extract source-labelled facts without claiming issuer authenticity or airworthiness."""
    filename = str(attachment.get("filename") or "attachment")
    content = attachment.get("content") or b""
    text = extract_attachment_text(
        filename, str(attachment.get("content_type") or "application/octet-stream"), content,
    )
    patterns = {
        "part_number": r"(?:part\s*(?:number|no\.?)|p/?n)\s*[:#]\s*([A-Z0-9][A-Z0-9._/-]*)",
        "serial_number": r"(?:serial\s*(?:number|no\.?)|s/?n)\s*[:#]\s*([A-Z0-9][A-Z0-9._/-]*)",
        "certificate_number": r"(?:certificate\s*(?:number|no\.?)|form\s+tracking\s+number)\s*[:#]\s*([A-Z0-9][A-Z0-9._/-]*)",
        "condition_code": r"(?:condition(?:\s*code)?|status/work)\s*[:#]\s*(NE|NS|OH|AR|SV|NEW|OVERHAULED|REPAIRED|INSPECTED|TESTED)\b",
        "issue_date": r"(?:issue\s*date|date\s*issued)\s*[:#]\s*([^\r\n]+)",
        "issuer": r"(?:issuer|issued\s*by|organisation\s*name|organization\s*name)\s*[:#]\s*([^\r\n]+)",
        "repair_station_number": r"(?:repair\s*station\s*(?:number|no\.?))\s*[:#]\s*([A-Z0-9][A-Z0-9._/-]*)",
    }
    facts = {}
    evidence = {}
    ambiguous_fields = []
    for field, pattern in patterns.items():
        matches = list(re.finditer(pattern, text, re.I))
        values = list(dict.fromkeys(match.group(1).strip().upper() for match in matches))
        if len(values) == 1:
            facts[field] = values[0]
            evidence[field] = matches[0].group(0)
        elif len(values) > 1:
            ambiguous_fields.append(field)
    if re.search(r"FAA\s+form\s+8130[-\s]?3", text, re.I) or (
        re.search(r"authorized\s+release\s+certificate", text, re.I)
        and re.search(r"8130[-\s]?3", text, re.I)
    ):
        document_type = DocumentType.FAA_8130_3
    elif re.search(r"EASA\s+form\s+1\b", text, re.I):
        document_type = DocumentType.EASA_FORM_1
    elif re.search(r"certificate\s+of\s+conform(?:ity|ance)", text, re.I):
        document_type = DocumentType.CERTIFICATE_OF_CONFORMITY
    else:
        document_type = DocumentType.UNKNOWN
    certificate_candidate = document_type != DocumentType.UNKNOWN or bool(re.search(
        r"cert|trace|8130|easa|form.?1|release|conform|logbook", filename, re.I,
    ))
    if filename.lower().endswith((".csv", ".xls", ".xlsx", ".xlsm")):
        certificate_candidate = False
        document_type = DocumentType.UNKNOWN
    return {
        "filename": filename,
        "sha256": hashlib.sha256(content).hexdigest(),
        "read_status": "READABLE" if text.strip() else "UNREADABLE",
        "document_type": document_type.value,
        "certificate_candidate": certificate_candidate,
        "facts": facts,
        "evidence": evidence,
        "ambiguous_fields": ambiguous_fields,
        "authenticity": "NOT_VERIFIED",
        "text": text,
    }


def compare_documents(
    attachments: list[dict[str, Any]], *, expected_part_number: str | None = None,
    expected_serial_number: str | None = None, expected_condition_code: str | None = None,
) -> dict[str, Any]:
    documents = [inspect_document(attachment) for attachment in attachments]
    discrepancies = []
    certificates = [document for document in documents if document["certificate_candidate"]]
    normalized_conditions = {"NEW": "NE", "OVERHAULED": "OH", "SERVICEABLE": "SV"}
    for document in certificates:
        name = document["filename"]
        if document["read_status"] != "READABLE":
            discrepancies.append(f"{name}: document is unreadable.")
        if document["document_type"] == DocumentType.UNKNOWN:
            discrepancies.append(f"{name}: certificate type is not recognized.")
        if document["ambiguous_fields"]:
            discrepancies.append(f"{name}: multiple values require item-level mapping: {', '.join(document['ambiguous_fields'])}.")
        if not document["facts"].get("part_number"):
            discrepancies.append(f"{name}: no unambiguous labelled part number was extracted.")
        expected = {
            "part_number": expected_part_number, "serial_number": expected_serial_number,
            "condition_code": expected_condition_code,
        }
        for field, target in expected.items():
            if not target:
                continue
            actual = document["facts"].get(field)
            wanted = str(target).strip().upper()
            if field == "condition_code":
                actual = normalized_conditions.get(actual, actual)
                wanted = normalized_conditions.get(wanted, wanted)
            if actual != wanted:
                discrepancies.append(f"{name}: {field} is missing or differs from the expected item.")
    for field in ("serial_number", "condition_code"):
        by_part: dict[str, set[str]] = {}
        for document in certificates:
            part = document["facts"].get("part_number")
            value = document["facts"].get(field)
            if part and value:
                by_part.setdefault(part, set()).add(normalized_conditions.get(value, value))
        for part, values in by_part.items():
            if len(values) > 1:
                discrepancies.append(f"{part}: documents disagree on {field}; verify the individual item mapping.")
    return {
        "status": "REVIEW_REQUIRED" if discrepancies else "FIELDS_CONSISTENT" if certificates else "NO_CERTIFICATE_EVIDENCE",
        "requires_human_review": bool(discrepancies) or not certificates,
        "authenticity": "NOT_VERIFIED",
        "discrepancies": discrepancies,
        "documents": documents,
    }
