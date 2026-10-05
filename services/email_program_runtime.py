"""Live email-program calls; backend records retain all commercial authority."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os

from schemas.extraction import PolicyEvaluationRecommendation, SupplierEmailDraft
from services.llm_provider import LLMRequest, LLMRouter

logger = logging.getLogger(__name__)


class EmailProgramRuntime:
    def __init__(self, router: LLMRouter | None = None):
        self._router = router
        self._router_injected = router is not None

    def _enabled(self) -> bool:
        enabled_values = {"1", "true", "yes", "on"}
        return (
            os.getenv("DSPY_ENABLED", "false").strip().lower() in enabled_values
            and (
                self._router_injected
                or os.getenv("LLM_LIVE_ENABLED", "false").strip().lower() in enabled_values
            )
        )

    @property
    def router(self) -> LLMRouter:
        if self._router is None:
            self._router = LLMRouter()
        return self._router

    @staticmethod
    def _request(task: str, instructions: str, facts: dict) -> LLMRequest:
        timeout = float(os.getenv("LLM_POLICY_EVALUATION_TIMEOUT_SECONDS", "8"))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("LLM_POLICY_EVALUATION_TIMEOUT_SECONDS must be positive and finite.")
        return LLMRequest(
            task=task,
            system_prompt=instructions,
            user_prompt=json.dumps(facts, ensure_ascii=False, sort_keys=True),
            model=os.getenv(
                "POLICY_EVALUATION_MODEL" if task == "policy_evaluation"
                else "SUPPLIER_COMMUNICATION_MODEL"
            ),
            temperature=0.0,
            timeout_seconds=timeout,
            max_tokens=1200,
            response_format="json",
        )

    async def evaluate_policy(self, facts: dict) -> dict:
        return await asyncio.to_thread(self._evaluate_policy, facts)

    def _evaluate_policy(self, facts: dict) -> dict:
        if not self._enabled():
            return {"status": "disabled"}
        try:
            request = self._request(
                "policy_evaluation",
                "Compare the supplied verified quote facts with active database policies. "
                "Missing facts remain unknown and require review. Return an advisory recommendation "
                "only; backend decisions and operator approvals remain authoritative. "
                "Never authorize dispatch or change any workflow state.",
                facts,
            )
            recommendation, response = self.router.extract_structured_with_response(
                request, PolicyEvaluationRecommendation, max_attempts=1,
            )
            return {
                "status": "available",
                **recommendation.model_dump(),
                "provider": response.provider,
                "model": response.model,
            }
        except Exception as exc:
            logger.warning("policy_advisory_evaluation_unavailable error=%s", type(exc).__name__)
            return {"status": "unavailable", "error": type(exc).__name__}

    def draft_supplier_request(
        self, subject: str, body: str, part_number: str, missing_fields: list[str],
    ) -> dict:
        canonical = {"subject": subject, "body": body}
        if not self._enabled():
            return {"status": "disabled", **canonical}
        try:
            request = self._request(
                "supplier_communication",
                "Draft this supplier clarification using the canonical subject and body. "
                "Copy the subject, all business content, part numbers, quantities, requested fields "
                "                and paragraph breaks exactly. The ONLY permitted changes are replacing the greeting line "
                "with 'Dear Supplier Team,' or 'Dear Supplier,' and replacing 'Best regards,' "
                "with 'Kind regards,'. Keep the signature unchanged. Return requested_fields "
                "exactly as supplied. Never add prices, discounts, deadlines or order commitments.",
                {
                    "canonical_subject": subject,
                    "canonical_body": body,
                    "part_number": part_number,
                    "requested_fields": missing_fields,
                },
            )
            draft, response = self.router.extract_structured_with_response(
                request, SupplierEmailDraft, max_attempts=1,
            )
            normalized_body = draft.body_text.strip()
            canonical_greeting = body.strip().split("\n", 1)[0]
            for greeting in ("Dear Supplier Team,", "Dear Supplier,"):
                if normalized_body.startswith(greeting + "\n\n"):
                    normalized_body = canonical_greeting + normalized_body[len(greeting):]
                    break
            head, sep, tail = normalized_body.rpartition("\n\nKind regards,\n")
            if sep and "\n" not in tail:
                normalized_body = f"{head}\n\nBest regards,\n{tail}"
            if (
                draft.subject != subject
                or normalized_body != body.strip()
                or draft.requested_fields != missing_fields
                or draft.confidence_score < 0.92
            ):
                raise ValueError("Supplier draft changed verified content or failed confidence validation.")
            return {
                "status": "available",
                "subject": draft.subject,
                "body": draft.body_text.strip(),
                "provider": response.provider,
                "model": response.model,
                "confidence_score": draft.confidence_score,
            }
        except Exception as exc:
            logger.warning("supplier_draft_unavailable_using_verified_template error=%s", type(exc).__name__)
            return {"status": "unavailable", "error": type(exc).__name__, **canonical}


email_program_runtime = EmailProgramRuntime()
