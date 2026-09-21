"""
RFQIntakeAgent
==============
Converts an unstructured customer RFQ (email, form, free text) into a fully
structured RFQIntakeOutput object.

Responsibilities
----------------
1. Parse natural-language RFQs using regex + keyword heuristics.
2. Normalize the Part Number (uppercase, collapsed whitespace, trimmed).
3. Detect missing mandatory fields.
4. Detect ambiguous information (e.g. multiple conditions offered).
5. Assign RFQ priority  (AOG > Urgent > Routine).
6. Generate a unique RFQ ID.
7. Return structured JSON via AgentResponse.data.

Required fields
---------------
- customer_name  (or company)
- part_number

Quantity defaults to one when the customer does not specify it.

If any mandatory field is absent, status is set to NEEDS_CLARIFICATION and
the field name is added to missing_fields.  The agent NEVER invents values.

Backward compatibility
----------------------
The orchestration_service.py pipeline consumes:
    res.data["customer_name"]
    res.data["customer_email"]
    res.data["items"]  (list of line-item dicts)

These keys are preserved alongside the new RFQIntakeOutput fields so the
existing workflow continues to function unchanged.
"""

import re
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

from agents.base_agent import BaseAgent, AgentMetadata, AgentResponse, EscalationRule
from models.db_models import RFQIntakeOutput


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MANDATORY_FIELDS = ["part_number", "quantity", "customer_name"]

# Valid condition codes and their common aliases
CONDITION_MAP: Dict[str, str] = {
    # Canonical codes
    "NE": "NE",
    "NS": "NS",
    "OH": "OH",
    "AR": "AR",
    # Written-out variants
    "NEW": "NE",
    "NEW SURPLUS": "NS",
    "OVERHAULED": "OH",
    "OVERHAUL": "OH",
    "AS REMOVED": "AR",
    "AS-REMOVED": "AR",
    "SERVICEABLE": "OH",
    "SV": "OH",
}

# Certification keyword → canonical label
CERT_PATTERNS: List[tuple] = [
    (r"FAA\s*(?:Form\s*)?8130[-\s]?3", "FAA 8130-3"),
    (r"EASA\s*Form\s*1",               "EASA Form 1"),
    (r"\bCoC\b",                        "CoC"),
    (r"Certificate\s+of\s+Conformance", "CoC"),
    (r"DFP",                            "DFP"),
    (r"TCCA",                           "TCCA"),
]

# AOG / urgent keyword patterns
AOG_RE    = re.compile(r"\bAOG\b", re.IGNORECASE)
URGENT_RE = re.compile(r"\b(urgent|asap|expedite|expedited|critical|immediate)\b", re.IGNORECASE)

# Date patterns (most common in aviation emails)
DATE_RE = re.compile(
    r"\b(?:by|before|no\s+later\s+than|NLT|need\s+by|required\s+by|required\s+date[:\s]*)?\s*"
    r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}"           # MM/DD/YYYY or DD-MM-YYYY
    r"|\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}"             # YYYY-MM-DD
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"  # Month DD YYYY
    r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})"  # DD Month YYYY
    r"\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _generate_rfq_id() -> str:
    """Generate a unique RFQ identifier."""
    return f"RFQ-{uuid.uuid4().hex[:8].upper()}"


def _normalize_part_number(raw: str) -> str:
    """
    Normalize a part number:
    - Strip surrounding whitespace.
    - Collapse internal whitespace to nothing (no spaces in PNs).
    - Convert to uppercase.
    - Preserve hyphens as they are structurally significant.
    """
    return re.sub(r"\s+", "", raw.strip()).upper()


def _extract_email(text: str) -> Optional[str]:
    """Extract the first e-mail address found in text."""
    m = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    return m.group(0) if m else None


def _extract_part_number(text: str) -> Optional[str]:
    """
    Heuristic extraction of aviation part numbers.

    Looks for explicit label first, then falls back to a general
    alphanumeric-with-hyphens pattern that is at least 5 characters.
    """
    metadata_tokens = {
        "HTTP-EQUIV", "CONTENT-TYPE", "CHARSET", "NAME", "CONTENT", "STYLE", "WIDTH", "HEIGHT",
        "UTF-8", "UTF8", "ISO-8859-1", "US-ASCII", "TEXT-HTML", "TEXT-PLAIN",
    }

    def valid_candidate(value: str) -> bool:
        normalized = _normalize_part_number(value)
        return (
            normalized not in metadata_tokens
            and not normalized.startswith(("RT-PBILL", "PBILL"))
            and bool(re.search(r"\d", normalized))
            and len(normalized) <= 40
            and bool(re.search(r"[A-Z0-9]+-[A-Z0-9]+", normalized))
        )

    # Explicit label patterns — stop at newline, pipe, comma, semicolon
    label_re = re.compile(
        r"(?:Part\s*(?:Number|No\.?|#)|P/?N|PN)[:\s#]*([A-Z0-9][A-Z0-9\- ]{2,30}?)(?:\s*[\n\r|,;. ]|\s+(?:Alt\s+Part\s+No\.?|Qty|Quantity|Condition|Cert|Required|Delivery|Additional|UOM)|\s*$)",
            re.IGNORECASE,
    )
    m = label_re.search(text)
    if m:
        candidate = _normalize_part_number(m.group(1))
        if valid_candidate(candidate):
            return candidate

    # General token: contains at least one digit and one hyphen, e.g. 060-1234-00
    general_re = re.compile(r"\b([A-Z0-9]{2,}(?:-[A-Z0-9]+){1,5})\b", re.IGNORECASE)
    candidates = general_re.findall(text)
    # Filter tokens that look like quantities ("5EA", "2EA") or dates
    for c in candidates:
        if re.match(r"^\d+[A-Z]{1,3}$", c, re.IGNORECASE):
            continue
        if len(c) >= 5 and valid_candidate(c):
            return _normalize_part_number(c)

    return None


def _extract_quantity(text: str) -> Optional[int]:
    """Extract a numeric quantity from common label patterns."""
    patterns = [
        r"(?:qty|quantity|q(?:t)?y\.?)[:\s#]*(\d+)",
        r"(\d+)\s*(?:ea|each|pcs?|pieces?|units?)\b",
        r"(?:need|require|want|request|order)\s+(\d+)",
        r"x\s*(\d+)\b",
        r"(\d+)\s*x\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def _extract_condition(text: str) -> tuple:
    """
    Returns (condition_code_or_None, is_ambiguous).

    Ambiguous when two or more distinct condition codes appear.
    """
    found_codes = []
    upper = text.upper()

    # Check longest aliases first to avoid partial matches (e.g. "NEW" before "NE")
    sorted_aliases = sorted(CONDITION_MAP.keys(), key=len, reverse=True)
    for alias in sorted_aliases:
        pattern = r"\b" + re.escape(alias) + r"\b"
        if re.search(pattern, upper):
            canonical = CONDITION_MAP[alias]
            if canonical not in found_codes:
                found_codes.append(canonical)

    if len(found_codes) == 0:
        return None, False
    if len(found_codes) == 1:
        return found_codes[0], False
    # Multiple distinct codes → ambiguous
    return "/".join(found_codes), True


def _extract_customer_info(text: str) -> tuple:
    """
    Returns (customer_name, company, email).

    Looks for common label patterns first; falls back to capitalized phrases.
    """
    customer_name: Optional[str] = None
    company: Optional[str] = None

    # Explicit labels
    name_m = re.search(
        r"(?:customer[ \t]*name|contact(?:[ \t]*name)?|name)[: \t]+([A-Za-z][\w \t\.\-]{1,50})",
        text, re.IGNORECASE
    )
    if name_m:
        customer_name = name_m.group(1).strip()

    company_m = re.search(
        r"(?:company|organization|org|airline|operator|mro)[: \t]+([A-Za-z][\w \t\.\-&,]{1,60})",
        text, re.IGNORECASE
    )
    if company_m:
        company = company_m.group(1).strip()
    else:
        from_m = re.search(r"from[: \t]+([^<\n\r]+)", text, re.IGNORECASE)
        if from_m:
            company = from_m.group(1).strip()

    # Fallback: pick the first Title-Cased multi-word token block as company
    if not company and not customer_name:
        caps_match = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4})\b", text)
        if caps_match:
            company = caps_match[0]

    email = _extract_email(text)
    if not company and email:
        domain = email.split("@", 1)[1].split(".", 1)[0]
        if domain.lower() not in {"gmail", "outlook", "hotmail", "yahoo", "icloud", "aol"}:
            company = domain.replace("-", " ").replace("_", " ").title()
    if not customer_name:
        signature = re.search(
            r"(?:best|kind regards|regards|sincerely|thank you)[,\s]*\n\s*([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,3})",
            text,
            re.IGNORECASE,
        )
        if signature:
            customer_name = signature.group(1).strip()
    return customer_name, company, email


def _extract_line_items(text: str) -> List[Dict[str, Any]]:
    """Extract repeated part rows with independent quantity and condition."""
    label_pattern = re.compile(
        r"(?:Part\s*(?:Number|No\.?|#)|P/?N|PN)[:\s#]*"
        r"([A-Z0-9][A-Z0-9\- ]{2,40}?)(?=\s+(?:Alt\s+Part\s+No\.?|Description|Condition|Qty|Quantity|Currency)|[\n\r|,;.]|\s*$)",
        re.IGNORECASE,
    )
    matches = list(label_pattern.finditer(text))
    items: List[Dict[str, Any]] = []
    for index, match in enumerate(matches):
        candidate = _normalize_part_number(match.group(1))
        if not candidate or len(candidate) > 40 or candidate.startswith(("RT-PBILL", "PBILL")):
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        segment = text[match.start():end]
        condition, ambiguous = _extract_condition(segment)
        items.append({
            "requested_part_number": candidate,
            "quantity": _extract_quantity(segment) or 1,
            "uom": "EA",
            "aircraft_type": None,
            "condition_preference": condition if condition and not ambiguous else "NE",
            "condition_ambiguous": ambiguous,
        })
    return items


def _extract_required_date(text: str) -> Optional[str]:
    """Return the first date expression found in the text."""
    m = DATE_RE.search(text)
    if m:
        # Return the captured date group (innermost group)
        for grp in m.groups():
            if grp:
                return grp.strip()
    return None


def _extract_delivery_location(text: str) -> Optional[str]:
    """Extract delivery destination from common label patterns."""
    m = re.search(
        r"(?:deliver(?:y)?\s*(?:to|location|address|destination)?|ship\s*to|send\s*to)[:\s]+([A-Za-z0-9][\w\s,\.\-]{2,80})",
        text, re.IGNORECASE
    )
    return m.group(1).strip() if m else None


def _extract_certifications(text: str) -> List[str]:
    """Extract all recognized certification requirements from text."""
    certs = []
    for pattern, label in CERT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE) and label not in certs:
            certs.append(label)
    return certs


def _extract_additional_requirements(text: str) -> Optional[str]:
    """
    Capture free-form notes that follow common additional-info labels.
    """
    m = re.search(
        r"(?:additional\s*(?:requirements?|notes?|info|remarks?)|special\s*instructions?|notes?)[:\s]+(.+?)(?:\n|$)",
        text, re.IGNORECASE
    )
    return m.group(1).strip() if m else None


def _determine_priority(aog: bool, text: str) -> str:
    if aog:
        return "AOG"
    if URGENT_RE.search(text):
        return "Urgent"
    return "Routine"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class RFQIntakeAgent(BaseAgent):
    """Convert unstructured customer RFQ text into structured RFQ data."""

    def __init__(self):
        metadata = AgentMetadata(
            name="RFQIntakeAgent",
            role="RFQ Intake Specialist",
            objective=(
                "Extract and structure RFQ metadata from unstructured customer text. "
                "Identify mandatory fields, detect ambiguity, assign priority, and "
                "generate a unique RFQ ID without inventing information."
            ),
            system_instruction=(
                "Analyze the raw customer RFQ text. "
                "Extract: customer_name, company, part_number (normalize to uppercase), "
                "quantity (integer), condition (NE/NS/OH/AR), required_date, "
                "delivery_location, AOG_status, certification_requirements, "
                "and additional_requirements. "
                "Flag missing mandatory fields (part_number, customer identity). "
                "Flag ambiguous condition when multiple codes appear. "
                "Set priority: AOG > Urgent > Routine. "
                "NEVER invent or guess missing fields."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "raw_text": {"type": "string", "description": "Raw email or RFQ text"}
                },
                "required": ["raw_text"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "rfq_id":                   {"type": "string"},
                    "status":                   {"type": "string", "enum": ["COMPLETE", "NEEDS_CLARIFICATION"]},
                    "customer_name":            {"type": ["string", "null"]},
                    "company":                  {"type": ["string", "null"]},
                    "part_number":              {"type": ["string", "null"]},
                    "quantity":                 {"type": ["integer", "null"]},
                    "condition":                {"type": ["string", "null"]},
                    "required_date":            {"type": ["string", "null"]},
                    "delivery_location":        {"type": ["string", "null"]},
                    "AOG_status":               {"type": "boolean"},
                    "certification_requirements": {"type": "array", "items": {"type": "string"}},
                    "additional_requirements":  {"type": ["string", "null"]},
                    "priority":                 {"type": "string"},
                    "missing_fields":           {"type": "array", "items": {"type": "string"}},
                    "ambiguous_fields":         {"type": "array", "items": {"type": "string"}},
                    # Legacy orchestration keys
                    "customer_email":           {"type": ["string", "null"]},
                    "items":                    {"type": "array"},
                },
                "required": ["rfq_id", "status", "priority", "missing_fields", "ambiguous_fields"],
            },
            available_tools=[],
            permissions=["create_rfq"],
            escalation_rules=[
                EscalationRule(
                    condition="missing_mandatory_fields",
                    action="halt_for_review",
                    escalate_to="human_operator",
                ),
                EscalationRule(
                    condition="ambiguous_condition",
                    action="halt_for_review",
                    escalate_to="human_operator",
                ),
            ],
            prompt_templates={
                "default": "Analyze the raw customer RFQ text. Extract: customer_name, company, part_number (normalize to uppercase), quantity (integer, default 1 when omitted), condition (NE/NS/OH/AR), required_date, delivery_location, AOG_status, certification_requirements, and additional_requirements. Flag missing mandatory fields (part_number, customer identity). Flag ambiguous condition when multiple codes appear. Set priority: AOG > Urgent > Routine. NEVER invent or guess confirmed fields.",
                "rfq_parse": "Normalize the inbound RFQ and return only confirmed fields; escalate when required information is missing or ambiguous.",
            },
        )
        super().__init__(metadata)

    # ------------------------------------------------------------------
    async def execute(
        self,
        inputs: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        raw_text: str = inputs.get("raw_text", "").strip()

        if not raw_text:
            return AgentResponse(
                success=False,
                error_message="Input 'raw_text' is empty or missing.",
                escalation_triggered=self.metadata.escalation_rules[0],
            )

        # ── 1. Extract all fields ───────────────────────────────────────
        rfq_id       = _generate_rfq_id()
        customer_name, company, customer_email = _extract_customer_info(raw_text)
        extracted_items = _extract_line_items(raw_text)
        part_number_raw = _extract_part_number(raw_text)
        part_number  = _normalize_part_number(part_number_raw) if part_number_raw else None
        extracted_quantity = _extract_quantity(raw_text)
        quantity     = extracted_quantity or 1
        quantity_defaulted = extracted_quantity is None
        condition, is_ambiguous_condition = _extract_condition(raw_text)
        if extracted_items:
            part_number = extracted_items[0]["requested_part_number"]
            quantity = extracted_items[0]["quantity"]
            condition = extracted_items[0]["condition_preference"]
            is_ambiguous_condition = any(item["condition_ambiguous"] for item in extracted_items)
        required_date    = _extract_required_date(raw_text)
        delivery_location = _extract_delivery_location(raw_text)
        aog_status   = bool(AOG_RE.search(raw_text))
        certifications   = _extract_certifications(raw_text)
        additional_req   = _extract_additional_requirements(raw_text)

        # ── 2. Priority ─────────────────────────────────────────────────
        priority = _determine_priority(aog_status, raw_text)

        # ── 3. Validation ───────────────────────────────────────────────
        missing_fields: List[str] = []
        ambiguous_fields: List[str] = []

        # Mandatory: some form of customer identity
        if not customer_name and not company:
            missing_fields.append("customer_name")

        if not part_number:
            missing_fields.append("part_number")

        if is_ambiguous_condition:
            ambiguous_fields.append("condition")

        # ── 4. Determine overall status ─────────────────────────────────
        needs_clarification = bool(missing_fields or ambiguous_fields)
        status = "NEEDS_CLARIFICATION" if needs_clarification else "COMPLETE"

        # ── 5. Build structured output ──────────────────────────────────
        intake_output = RFQIntakeOutput(
            rfq_id=rfq_id,
            status=status,
            customer_name=customer_name,
            company=company,
            part_number=part_number,
            quantity=quantity,
            condition=condition if not is_ambiguous_condition else condition,
            required_date=required_date,
            delivery_location=delivery_location,
            AOG_status=aog_status,
            certification_requirements=certifications,
            additional_requirements=additional_req or "",
            priority=priority,
            missing_fields=missing_fields,
            ambiguous_fields=ambiguous_fields,
        )

        # ── 6. Build legacy-compatible items list ───────────────────────
        items: list = extracted_items or []
        if not items and part_number and quantity:
            items.append({
                "requested_part_number": part_number,
                "quantity": quantity,
                "uom": "EA",
                "aircraft_type": None,
                "condition_preference": condition if (condition and not is_ambiguous_condition) else "NE",
            })
        for item in items:
            item.pop("condition_ambiguous", None)

        # ── 7. Compose response payload ─────────────────────────────────
        payload = intake_output.model_dump()
        payload["quantity_defaulted"] = quantity_defaulted
        payload["customer_email"] = customer_email  # legacy key
        payload["items"] = items                    # legacy key

        # ── 8. Return ───────────────────────────────────────────────────
        if needs_clarification:
            escalation = (
                self.metadata.escalation_rules[1]
                if ambiguous_fields and not missing_fields
                else self.metadata.escalation_rules[0]
            )
            return AgentResponse(
                success=False,
                data=payload,
                error_message=(
                    f"RFQ requires clarification. "
                    f"Missing: {missing_fields or 'none'}. "
                    f"Ambiguous: {ambiguous_fields or 'none'}."
                ),
                escalation_triggered=escalation,
            )

        return AgentResponse(success=True, data=payload)
