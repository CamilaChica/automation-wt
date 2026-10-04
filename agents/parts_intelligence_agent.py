import re
from typing import Dict, Any, Optional
from agents.base_agent import BaseAgent, AgentMetadata, AgentResponse, EscalationRule
from tools.tool_interfaces import SearchPartsCatalogTool
from services.agents.prompts import SOURCING_PROMPT

# Part number must contain only alphanumeric characters and hyphens, minimum 3 chars
_PN_FORMAT_REGEX = re.compile(r"^[A-Z0-9][A-Z0-9\-]{1,}[A-Z0-9]$")


class PartsIntelligenceAgent(BaseAgent):
    """
    Validates aerospace part numbers against persisted inventory and supplier offers.

    Rules:
    - Search exact Part Number matches in persisted operational records.
    - Return only product information present in those records.
    - Never infer approved alternate parts.
    - Provide a confidence score: 1.0 (exact), 0.0 (not found).
    - Flag unknown Part Numbers (confidence 0.0, is_valid False).
    - Never assume compatibility or alternates.
    """

    def __init__(self):
        metadata = AgentMetadata(
            name="PartsIntelligenceAgent",
            role="Aerospace Parts Catalog Validator",
            objective=(
                "Validate requested part numbers against persisted inventory and supplier "
                "offer records. Return only recorded details; flag unknown part numbers "
                "for human review."
            ),
            system_instruction=SOURCING_PROMPT,
            input_schema={
                "type": "object",
                "properties": {
                    "requested_part_number": {
                        "type": "string",
                        "description": "Part number as submitted in the RFQ"
                    }
                },
                "required": ["requested_part_number"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "resolved_part_number": {"type": "string"},
                    "description": {"type": "string"},
                    "manufacturer": {"type": "string"},
                    "category": {"type": "string"},
                    "aircraft_applicability": {"type": "string"},
                    "condition": {"type": "string"},
                    "alternate_part_numbers": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "documentation_requirements": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "match_type": {
                        "type": "string",
                        "description": "exact | none"
                    },
                    "is_valid": {"type": "boolean"},
                    "confidence_score": {
                        "type": "number",
                        "description": "1.0 = exact database record, 0.0 = not found"
                    }
                },
                "required": ["resolved_part_number", "is_valid", "confidence_score", "match_type"]
            },
            available_tools=["search_parts_catalog"],
            permissions=["read_catalog"],
            escalation_rules=[
                EscalationRule(
                    condition="ambiguous_part_match",
                    action="halt_for_review",
                    escalate_to="human_operator"
                ),
                EscalationRule(
                    condition="invalid_part_format",
                    action="halt_for_review",
                    escalate_to="human_operator"
                ),
                EscalationRule(
                    condition="part_not_found",
                    action="halt_for_review",
                    escalate_to="human_operator"
                )
            ],
            prompt_templates={
                "default": "Inspect the part number from the validated RFQ and search persisted inventory and supplier-offer records for an exact match. Never infer compatibility, product details, or alternate part numbers. If the exact part is not recorded, flag it and escalate for human review.",
                "catalog_lookup": "Return only exact part-number matches and details present in persisted inventory or supplier-offer records.",
            }
        )
        super().__init__(metadata)
        self._catalog_tool = SearchPartsCatalogTool()

    async def execute(
        self,
        inputs: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> AgentResponse:

        raw_pn: str = inputs.get("requested_part_number", "")
        req_pn: str = raw_pn.strip().upper()

        # ── 1. FORMAT VALIDATION ─────────────────────────────────────────────
        if not req_pn or len(req_pn) < 3 or not _PN_FORMAT_REGEX.match(req_pn):
            return AgentResponse(
                success=False,
                error_message=(
                    f"Part number '{raw_pn}' fails format validation. "
                    "Expected alphanumeric characters and hyphens, minimum 3 characters, "
                    "no leading/trailing hyphens, and no special characters (e.g. '/')."
                ),
                escalation_triggered=self.metadata.escalation_rules[1]  # invalid_part_format
            )

        # ── 2. CATALOG SEARCH ────────────────────────────────────────────────
        catalog_result = await self._catalog_tool.run({"part_number": req_pn})

        found: bool = catalog_result.get("found", False)
        match_type: str = catalog_result.get("match_type", "none")
        matched_parts: list = catalog_result.get("parts", [])

        # ── 3. AMBIGUOUS / MULTIPLE MATCH ────────────────────────────────────
        if match_type == "multiple":
            ambiguous_pns = [p["part_number"] for p in matched_parts]
            return AgentResponse(
                success=False,
                error_message=(
                    f"Part number '{req_pn}' is ambiguous — it matches multiple catalog entries: "
                    f"{', '.join(ambiguous_pns)}. Human review required to select the correct part."
                ),
                escalation_triggered=self.metadata.escalation_rules[0]  # ambiguous_part_match
            )

        # ── 4. KNOWN PART — EXACT / FUZZY / ALTERNATE MATCH ─────────────────
        if found and matched_parts:
            part = matched_parts[0]

            # Confidence is determined solely by match quality, never assumed
            confidence_map = {"exact": 1.0}
            confidence_score = confidence_map.get(match_type, 0.0)

            approved_alternates = part.get("alternate_part_numbers", [])

            return AgentResponse(
                success=True,
                data={
                    "resolved_part_number": part["part_number"],
                    "description": part.get("description", ""),
                    "manufacturer": part.get("manufacturer", ""),
                    "category": part.get("category", ""),
                    "aircraft_applicability": part.get("aircraft_applicability", ""),
                    "condition": part.get("condition", ""),
                    "alternate_part_numbers": approved_alternates,
                    "documentation_requirements": part.get("documentation_requirements", []),
                    "match_type": match_type,
                    "is_valid": True,
                    "confidence_score": confidence_score
                }
            )

        # ── 5. UNKNOWN PART NUMBER ───────────────────────────────────────────
        return AgentResponse(
            success=False,
            data={
                "resolved_part_number": req_pn,
                "description": "",
                "manufacturer": "",
                "category": "",
                "aircraft_applicability": "",
                "condition": "",
                "alternate_part_numbers": [],
                "documentation_requirements": [],
                "match_type": "none",
                "is_valid": False,
                "confidence_score": 0.0
            },
            error_message=(
                f"Part number '{req_pn}' was not found in persisted inventory or supplier offers. "
                "Cannot proceed — part compatibility must never be assumed."
            ),
            escalation_triggered=self.metadata.escalation_rules[2]  # part_not_found
        )
