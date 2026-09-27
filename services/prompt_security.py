"""Input sanitization, PII masking, and prompt-injection detection."""

from __future__ import annotations

import re

from schemas.rag import PromptSecurity, SecurityInspection


class InputSecurityError(ValueError):
    def __init__(self, inspection: SecurityInspection):
        super().__init__("Input was blocked by prompt security policy.")
        self.inspection = inspection


class PromptSecurityService:
    _INJECTION_PATTERNS = (
        re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions\b", re.IGNORECASE),
        re.compile(r"\bdisregard\s+(?:all\s+)?(?:previous|prior|above)\s+instructions\b", re.IGNORECASE),
        re.compile(r"\b(?:reveal|print|show)\s+(?:the\s+)?system prompt\b", re.IGNORECASE),
        re.compile(r"\b(?:jailbreak|developer mode|DAN mode)\b", re.IGNORECASE),
        re.compile(r"\byou are now\s+(?:DAN|an? unrestricted)", re.IGNORECASE),
    )
    _EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
    _PHONE_PATTERN = re.compile(
        r"(?<!\w)(?:\+\d{1,3}[ .-]?)?\(\d{3}\)[ .-]\d{3}[ .-]\d{4}(?!\w)"
        r"|(?<!\w)\+\d{1,3}[ .-]\d{3}[ .-]\d{3}[ .-]\d{4}(?!\w)"
    )
    _LABELED_PHONE_PATTERN = re.compile(
        r"\b(?P<label>phone|telephone|tel|call)\s*[:#-]?\s*(?P<number>\d{3}[ .-]\d{3}[ .-]\d{4})\b",
        re.IGNORECASE,
    )
    _CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

    def inspect(self, text: str, policy: PromptSecurity | None = None) -> SecurityInspection:
        policy = policy or PromptSecurity()
        sanitized = self._CONTROL_PATTERN.sub("", text).strip() if policy.sanitize_input else text
        injection = policy.detect_injection and any(pattern.search(sanitized) for pattern in self._INJECTION_PATTERNS)
        findings = ["prompt_injection_or_jailbreak"] if injection else []
        pii_matches = bool(
            self._EMAIL_PATTERN.search(sanitized)
            or self._PHONE_PATTERN.search(sanitized)
            or self._LABELED_PHONE_PATTERN.search(sanitized)
        )
        if policy.mask_pii:
            sanitized = self._EMAIL_PATTERN.sub("[EMAIL REDACTED]", sanitized)
            sanitized = self._LABELED_PHONE_PATTERN.sub(
                lambda match: f"{match.group('label')} [PHONE REDACTED]", sanitized
            )
            sanitized = self._PHONE_PATTERN.sub("[PHONE REDACTED]", sanitized)
        if pii_matches:
            findings.append("pii_masked")
        return SecurityInspection(
            sanitized_text=sanitized,
            detected_injection=injection,
            detected_pii=pii_matches,
            blocked=injection and policy.prevent_jailbreaks and policy.block_injection,
            findings=findings,
        )

    def enforce(self, text: str, policy: PromptSecurity | None = None) -> SecurityInspection:
        inspection = self.inspect(text, policy)
        if inspection.blocked:
            raise InputSecurityError(inspection)
        return inspection