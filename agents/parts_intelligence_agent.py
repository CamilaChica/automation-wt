import re
from typing import Dict, Any, Optional
from agents.base_agent import BaseAgent, AgentMetadata, AgentResponse, EscalationRule
from tools.tool_interfaces import SearchPartsCatalogTool
from services.agents.prompts import SOURCING_PROMPT

# Part number must contain only alphanumeric characters and hyphens, minimum 3 chars
_PN_FORMAT_REGEX = re.compile(r"^[A-Z0-9][A-Z0-9\-]{1,}[A-Z0-9]$")


class PartsIntelligenceAgent(BaseAgent):
    """
    Validates aerospace Part Numbers against the master parts catalog.

    Rules:
    - Search exact Part Number matches first.
    - Return full product information when found.
    - Identify approved alternate parts from catalog data (never assumed).
    - Provide a confidence score: 1.0 (exact), 0.9 (fuzzy), 0.8 (alternate).
    - Flag unknown Part Numbers (confidence 0.0, is_valid False).
    - Never assume compatibility — alternates come only from explicit catalog entries.
    """

    def __init__(self):
        metadata = AgentMetadata(
            name="PartsIntelligenceAgent",
            role="Aerospace Parts Catalog Validator",
            objective=(
                "Validate and normalize requested part numbers against the master "
                "aviation parts catalog. Return full product details, approved alternates, "
                "and a confidence score. Flag any unknown or ambiguous part numbers for "
                "human review."
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
                        "description": "exact | fuzzy | alternate | none"
                    },
                    "is_valid": {"type": "boolean"},
                    "confidence_score": {
                        "type": "number",
                        "description": "1.0 = exact, 0.9 = fuzzy/normalized, 0.8 = alternate, 0.0 = unknown"
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
                )
            ],
            prompt_templates={
                "default": "Inspect part numbers from the validated RFQ. Standardize hyphenation, spacing, and casing before lookup. Search the parts catalog for exact matches first, then normalized/fuzzy matches, then alternate PNs. Never assume compatibility — only return alternates explicitly listed in the catalog entry. If multiple parts match ambiguously, halt for human review. If the part is entirely unknown, flag it and escalate.",
                "catalog_lookup": "Validate the part against the master aviation parts catalog and return only explicit matches or approved alternates.",
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
            confidence_map = {
                "exact":     1.0,
                "fuzzy":     0.9,
                "alternate": 0.8,
            }
            confidence_score = confidence_map.get(match_type, 0.0)

            # Approved alternates come ONLY from the catalog entry — never assumed
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
                f"Part number '{req_pn}' was not found in the master aviation parts catalog. "
                "Cannot proceed — part compatibility must never be assumed."
            ),
            escalation_triggered=self.metadata.escalation_rules[1]  # invalid_part_format
        )
