import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agents.base_agent import BaseAgent, AgentMetadata, AgentResponse
from services.communication_service import communication_service
from services.llm_provider import LLMRequest, LLMRouter
from services.operations_store import operations_store
from services.agents.prompts import CUSTOMER_COMMUNICATION_PROMPT

logger = logging.getLogger(__name__)
CUSTOMER_COMMUNICATION_PROMPT_VERSION = "customer-communication-v1"
CUSTOMER_COMMUNICATION_MODEL_COST_PER_MILLION = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}


class GeneratedEmailDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(..., min_length=5, max_length=200)
    body_text: str = Field(..., min_length=20)
    body_html: str = Field(..., min_length=20)
    redacted_fields_applied: List[str] = Field(default_factory=list)
    confidence_score: float = Field(..., ge=0.0, le=1.0)

    @field_validator("subject", "body_text", "body_html")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Generated email content cannot be blank.")
        return cleaned


class CustomerCommunicationAgent(BaseAgent):
    def __init__(self, llm_router: LLMRouter | None = None):
        metadata = AgentMetadata(
            name="CustomerCommunicationAgent",
            role="Customer Relationship Communication Specialist",
            objective="Draft and transmit professional communications regarding quote details to clients.",
            system_instruction=CUSTOMER_COMMUNICATION_PROMPT,
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            available_tools=["email_sender_service", "llm_provider"],
            permissions=["send_emails"],
            escalation_rules=[],
            prompt_templates={"customer_quote": "Draft a validated customer quotation email."},
        )
        super().__init__(metadata)
        self._router_injected = llm_router is not None
        self.llm_router = llm_router or LLMRouter()
        self.llm_timeout_seconds = float(os.getenv("LLM_EMAIL_TIMEOUT_SECONDS", "12"))
        self.llm_model = os.getenv("CUSTOMER_COMMUNICATION_MODEL") or os.getenv("OPENAI_MODEL")
        self.template_fallback_enabled = os.getenv("LLM_ALLOW_TEMPLATE_FALLBACK", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.llm_live_enabled = os.getenv("LLM_LIVE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        provider_name = self.llm_router.task_providers.get("customer_communication", os.getenv("LLM_DEFAULT_PROVIDER", "openai"))
        if provider_name not in self.llm_router.providers:
            raise ValueError(f"Unknown customer communication LLM provider: {provider_name}")
        logger.info("customer_communication_llm_configured provider=%s model=%s timeout_seconds=%s", provider_name, self.llm_model or "provider-default", self.llm_timeout_seconds)

    def _format_quote_summary(self, quote_details: Dict[str, Any]) -> str:
        quote_id = quote_details.get("quote_id", "")
        total = float(quote_details.get("total_amount", 0.0) or 0.0)
        subtotal = float(quote_details.get("subtotal", total) or 0.0)
        lines = [f"Quote ID: {quote_id}", f"Subtotal: ${subtotal:,.2f}", "Shipping: customer-selected, not quoted by Winged Tycoons", f"Total: ${total:,.2f}", "", "Line items:"]
        for item in quote_details.get("items") or []:
            quantity = int(item.get("quantity", 0) or 0)
            unit_price = float(item.get("unit_price", 0.0) or 0.0)
            attachments = item.get("attachments") or []
            attachment_text = f" | Attachments: {', '.join(map(str, attachments))}" if attachments else ""
            lines.append(f"- {item.get('part_number', 'N/A')} | Qty {quantity} {item.get('uom') or 'EA'} | Unit price ${unit_price:,.2f} | Line total ${quantity * unit_price:,.2f}{attachment_text}")
        return "\n".join(lines).strip()

    def _emergency_template(self, name: str, quote_id: str, summary: str) -> GeneratedEmailDraft:
        quantity_question = "\n\nHow many do you need?" if self._quantity_was_defaulted else ""
        return GeneratedEmailDraft(
            subject=f"Winged Tycoons quotation {quote_id}",
            body_text=(f"Dear {name},\n\nPlease find your approved quotation {quote_id} below.\n\n{summary}{quantity_question}\n\nPlease reply to this email with any questions or a purchase order.\n\nBest regards,\nWinged Tycoons Sales Team"),
            body_html="<p>Approved quotation details are included in the plain-text version of this message.</p>",
            redacted_fields_applied=["supplier costs", "internal margins", "supplier identities", "warehouse locations"],
            confidence_score=1.0,
        )

    async def execute(self, inputs: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        email = inputs.get("customer_email", "")
        name = inputs.get("customer_name", "")
        details = inputs.get("quote_details", {})
        self._quantity_was_defaulted = bool(details.get("quantity_defaulted", False))
        quote_id = details.get("quote_id", "")
        summary = self._format_quote_summary(details)
        request = LLMRequest(
            task="customer_communication",
            system_prompt=(f"{CUSTOMER_COMMUNICATION_PROMPT} "
                           "Redact supplier costs, internal margins, supplier identities, warehouse locations, credentials, and private audit data. "
                           "Do not invent facts. If quantity_defaulted is true, ask exactly: How many do you need? "
                           "Return exactly the JSON schema."),
            user_prompt=json.dumps({"untrusted_quote_data": {
                "customer_name": name,
                "quote_details": details,
                "approved_quote_summary": summary,
            }}, ensure_ascii=False, default=str),
            model=self.llm_model,
            temperature=float(os.getenv("CUSTOMER_COMMUNICATION_TEMPERATURE", "0.2")),
            timeout_seconds=self.llm_timeout_seconds,
            max_tokens=int(os.getenv("CUSTOMER_COMMUNICATION_MAX_TOKENS", "1200")),
            response_format="json",
        )
        started = time.perf_counter()
        fallback_used = False
        usage: dict[str, Any] = {}
        try:
            if not self.llm_live_enabled and not self._router_injected:
                raise RuntimeError("Live LLM drafting is disabled; using emergency template.")
            draft, response = await asyncio.wait_for(
                asyncio.to_thread(self.llm_router.extract_structured_with_response, request, GeneratedEmailDraft),
                timeout=self.llm_timeout_seconds + 2,
            )
            usage = response.raw.get("usage", {}) if isinstance(response.raw, dict) else {}
            logger.info("llm_email_draft status=success provider=%s model=%s latency_ms=%s prompt_tokens=%s completion_tokens=%s", response.provider, response.model, round((time.perf_counter() - started) * 1000, 2), usage.get("prompt_tokens", usage.get("input_tokens")), usage.get("completion_tokens", usage.get("output_tokens")))
        except Exception as exc:
            fallback_used = True
            logger.exception("llm_email_draft status=failure quote_id=%s fallback_enabled=%s", quote_id, self.template_fallback_enabled)
            if not self.template_fallback_enabled:
                return AgentResponse(success=False, error_message=f"LLM email drafting failed: {type(exc).__name__}: {exc}")
            draft = self._emergency_template(name, quote_id, summary)
            response = None

        model_id = response.model if response else "template-fallback"
        input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
        input_rate, output_rate = CUSTOMER_COMMUNICATION_MODEL_COST_PER_MILLION.get(model_id, (0.0, 0.0))
        operations_store.record_llm_telemetry(
            task="customer_communication",
            prompt_version=CUSTOMER_COMMUNICATION_PROMPT_VERSION,
            model_id=model_id,
            model_calls=[model_id] if response else [],
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=(input_tokens * input_rate + output_tokens * output_rate) / 1_000_000,
            validation_result="VALIDATED" if response else "TEMPLATE_FALLBACK",
        )

        operations_store.record_automation_event(
            event_type="llm_email_draft",
            entity_type="quote",
            entity_id=quote_id,
            status="FALLBACK" if fallback_used else "SUCCESS",
            result=json.dumps({
                "provider": response.provider if response else None,
                "model": response.model if response else None,
                "fallback_used": fallback_used,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "usage": usage,
            }),
        )
        try:
            transmission = communication_service.send_customer_quote(
                recipient=email,
                customer_name=name,
                quote_id=quote_id,
                quote_summary=summary,
                reply_to=inputs.get("reply_to"),
                quote_items=details.get("items") or None,
                subject_override=draft.subject,
                body_override=draft.body_text,
            )
        except Exception as exc:
            logger.exception("customer_email_dispatch status=failure quote_id=%s error=%s", quote_id, type(exc).__name__)
            return AgentResponse(
                success=False,
                error_message=f"Customer email delivery failed: {type(exc).__name__}: {exc}",
                data={"formatted_body": draft.body_text, "subject": draft.subject, "llm_fallback_used": fallback_used},
            )
        return AgentResponse(success=True, data={
            "communication_logged": True,
            "transmission_status": transmission["transmission_status"],
            "formatted_body": draft.body_text,
            "subject": draft.subject,
            "body_html": draft.body_html,
            "redacted_fields_applied": draft.redacted_fields_applied,
            "confidence_score": draft.confidence_score,
            "llm_fallback_used": fallback_used,
        })

    def generate_quote_email(self, quote_data: dict) -> str:
        summary = quote_data.get("pdf_summary", f"Total Amount: ${float(quote_data.get('total_amount', 0.0)):,.2f}")
        return self._emergency_template("Customer", quote_data.get("quote_id", ""), summary).body_text
