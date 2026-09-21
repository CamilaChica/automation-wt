"""Deterministic export-control screening boundary.

This is a local policy gate, not a replacement for live BIS/OFAC/ITAR screening.
"""

from __future__ import annotations

import os
import re
from pydantic import BaseModel, Field


class ExportScreeningResult(BaseModel):
    blocked: bool
    reasons: list[str] = Field(default_factory=list)
    requires_euc: bool = False


class ExportControlService:
    def __init__(self):
        self.denied_entities = self._load_terms("EXPORT_DENIED_ENTITIES", {"blacklisted co", "sanctioned entity"})
        self.denied_countries = self._load_terms("EXPORT_DENIED_COUNTRIES", {"north korea", "iran", "syria"})
        self.restricted_part_prefixes = tuple(
            value.strip().upper()
            for value in os.getenv("EXPORT_RESTRICTED_PART_PREFIXES", "MIL-,ITAR-").split(",")
            if value.strip()
        )

    def screen(self, *, customer_name: str, raw_text: str, destination: str | None = None, part_number: str | None = None) -> ExportScreeningResult:
        searchable = " ".join(filter(None, [customer_name, raw_text, destination, part_number])).lower()
        reasons = []
        for entity in self.denied_entities:
            if entity in searchable:
                reasons.append(f"Denied entity match: {entity}")
        for country in self.denied_countries:
            if re.search(rf"\b{re.escape(country)}\b", searchable):
                reasons.append(f"Denied destination/country match: {country}")

        normalized_part = (part_number or "").upper()
        restricted_in_text = any(
            prefix.upper() in (raw_text or "").upper()
            for prefix in self.restricted_part_prefixes
        )
        requires_euc = bool(
            normalized_part.startswith(self.restricted_part_prefixes)
            or restricted_in_text
        )
        if requires_euc:
            reasons.append("Restricted or dual-use part requires end-user certification.")
        return ExportScreeningResult(blocked=bool(reasons), reasons=reasons, requires_euc=requires_euc)

    @staticmethod
    def _load_terms(environment_name: str, defaults: set[str]) -> set[str]:
        configured = os.getenv(environment_name, "")
        return {value.strip().lower() for value in configured.split(",") if value.strip()} or defaults


export_control_service = ExportControlService()
