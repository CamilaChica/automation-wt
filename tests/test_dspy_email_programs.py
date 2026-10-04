from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from services.business_policy_retriever import (
    BusinessPolicyRetrievalError,
    retrieve_active_business_policies,
)
from services.dspy_email_programs import (
    SIGNATURES,
    load_training_data,
    predict_structured,
)
from schemas.extraction import PolicyEvaluationRecommendation
from services.llm_provider import LLMRequest, LLMResponse, LLMRouter
from services.email_program_runtime import EmailProgramRuntime
from schemas.extraction import SupplierEmailDraft


class TestEmailProgramRuntime(unittest.TestCase):
    def test_supplier_draft_preserves_verified_content_or_uses_logged_template(self):
        subject = "Supplier information needed"
        body = "Hello,\n\nPlease confirm PN SYNTHETIC-001 and quantity 2 EA.\n\nBest regards,\nWinged Tycoons Purchasing Team"
        router = MagicMock()
        runtime = EmailProgramRuntime(router)
        for generated_body, expected_status in (
            (body.replace("Hello,", "Dear Supplier Team,"), "available"),
            (body.replace("quantity 2", "quantity 20"), "unavailable"),
        ):
            with self.subTest(expected_status=expected_status):
                router.extract_structured_with_response.return_value = (
                    SupplierEmailDraft(
                        subject=subject, body_text=generated_body,
                        requested_fields=["certificate"], confidence_score=0.99,
                    ),
                    LLMResponse("openai", "test-model", "{}", {}),
                )
                with patch.dict("os.environ", {"DSPY_ENABLED": "true"}):
                    result = runtime.draft_supplier_request(
                        subject, body, "SYNTHETIC-001", ["certificate"]
                    )
                self.assertEqual(result["status"], expected_status)
                self.assertEqual(result["body"], generated_body if expected_status == "available" else body)

    def test_policy_provider_failure_is_explicit_and_live_calls_are_opt_in(self):
        router = MagicMock()
        router.extract_structured_with_response.side_effect = TimeoutError("synthetic timeout")
        with patch.dict("os.environ", {"DSPY_ENABLED": "true"}):
            result = asyncio.run(EmailProgramRuntime(router).evaluate_policy({"total_amount": 1000}))
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["error"], "TimeoutError")
        with patch.dict("os.environ", {"DSPY_ENABLED": "true", "LLM_LIVE_ENABLED": "false"}):
            result = asyncio.run(EmailProgramRuntime().evaluate_policy({"total_amount": 1000}))
        self.assertEqual(result["status"], "disabled")

    def test_main_quote_workflow_persists_advisory_without_changing_quote(self):
        from services.orchestration_service import OrchestrationService

        service = object.__new__(OrchestrationService)
        quote = {"id": "SYNTHETIC-Q1", "total_amount": 1000, "status": "Pending_Approval"}
        original = dict(quote)
        advisory = {"status": "available", "decision": "reject"}
        with (
            patch("services.orchestration_service.email_program_runtime.evaluate_policy",
                  new=AsyncMock(return_value=advisory)) as evaluate,
            patch("services.orchestration_service.db_service.add_audit_log") as audit,
        ):
            result = asyncio.run(service._record_quote_policy_advisory("SYNTHETIC-R1", quote, []))
        self.assertEqual(result, advisory)
        self.assertEqual(quote, original)
        self.assertIsNone(evaluate.call_args.args[0]["sanctions_clear"])
        self.assertIsNone(evaluate.call_args.args[0]["extraction_confidence"])
        audit.assert_called_once()

        repositories = SimpleNamespace(rfq=SimpleNamespace(add_audit_log=AsyncMock()))
        with patch("services.orchestration_service.email_program_runtime.evaluate_policy",
                   new=AsyncMock(return_value=advisory)):
            asyncio.run(service._record_quote_policy_advisory(
                "SYNTHETIC-R1", quote, [], repositories=repositories, operator_name="synthetic-operator",
            ))
        repositories.rfq.add_audit_log.assert_awaited_once()
        self.assertEqual(quote, original)

    def test_live_supplier_draft_is_wired_to_outbox_and_keeps_thread_and_deduplication(self):
        from services.communication_service import CommunicationService

        service = CommunicationService()
        repositories = SimpleNamespace(records=SimpleNamespace(
            enqueue_outbox_message=AsyncMock(return_value={"status": "pending", "id": "SYNTHETIC-OUT1"}),
            record_automation_event=AsyncMock(),
        ))
        body = service._missing_fields_request("SYNTHETIC-001", ["certificate"])
        generated_body = body.replace("Hello,", "Dear Supplier Team,")
        subject = "Re: RFQ request: SYNTHETIC-001 - information needed"
        with (
            patch("services.communication_service.ensure_staging_recipient_allowed"),
            patch("services.communication_service.email_program_runtime.draft_supplier_request",
                  return_value={"status": "available", "subject": subject, "body": generated_body}),
        ):
            result = asyncio.run(service.request_missing_supplier_fields_async(
                repositories, "supplier@example.invalid", "SYNTHETIC-001", ["certificate"],
                reply_to="synthetic-thread", entity_id="SYNTHETIC-R1",
            ))
        queued = repositories.records.enqueue_outbox_message.call_args.kwargs
        self.assertEqual(queued["body"], generated_body)
        self.assertEqual(queued["reply_to"], "synthetic-thread")
        self.assertEqual(queued["deduplication_key"], service._supplier_info_key(
            "supplier@example.invalid", "SYNTHETIC-001",
        ))
        self.assertEqual(result["draft_generation"]["status"], "available")
        repositories.records.record_automation_event.assert_awaited_once()

    def test_automatic_supplier_outreach_has_stable_per_rfq_keys(self):
        from services.communication_service import CommunicationService

        service = CommunicationService()
        suppliers = [{"company_name": "Synthetic Supplier", "email": "supplier@example.invalid"}]

        def canonical_draft(subject, body, _part, _fields):
            return {"status": "available", "subject": subject, "body": body}

        with (
            patch("services.communication_service.operations_store") as store,
            patch("services.communication_service.email_program_runtime.draft_supplier_request",
                  side_effect=canonical_draft) as draft,
            patch.object(service, "_send", return_value={"transmission_status": "PENDING"}) as send,
            patch.dict("os.environ", {"SUPPLIER_REQUEST_RECIPIENTS": ""}),
        ):
            store.storage_engine = "postgresql"
            store.list_suppliers.return_value = suppliers
            first = service.request_part_quotes("SYNTHETIC-001", 2, rfq_id="RFQ-SYNTHETIC-1")
            first_key = send.call_args.kwargs["deduplication_key"]
            service.request_part_quotes("SYNTHETIC-001", 2, rfq_id="RFQ-SYNTHETIC-1")
            self.assertEqual(send.call_args.kwargs["deduplication_key"], first_key)
            service.request_part_quotes("SYNTHETIC-001", 2, rfq_id="RFQ-SYNTHETIC-2")
            self.assertNotEqual(send.call_args.kwargs["deduplication_key"], first_key)
            self.assertEqual(send.call_args.kwargs["entity_id"], "RFQ-SYNTHETIC-2")
            self.assertEqual(first[0]["draft_generation"]["status"], "available")
            self.assertEqual(draft.call_count, 3)

    def test_automatic_stale_confirmation_retains_supplier_thread_and_deduplication(self):
        from services.communication_service import CommunicationService

        service = CommunicationService()
        with (
            patch("services.communication_service.email_program_runtime.draft_supplier_request",
                  side_effect=lambda subject, body, _part, _fields: {
                      "status": "available", "subject": subject, "body": body,
                  }),
            patch.object(service, "_send", return_value={"transmission_status": "PENDING"}) as send,
        ):
            for _ in range(2):
                service.request_stale_supplier_confirmation(
                    "supplier@example.invalid", "Synthetic Supplier", "SYNTHETIC-001", 2,
                    reply_to="synthetic-supplier-thread", rfq_id="RFQ-SYNTHETIC-1",
                )
            self.assertEqual(send.call_args.kwargs["reply_to"], "synthetic-supplier-thread")
            self.assertEqual(
                send.call_args_list[0].kwargs["deduplication_key"],
                send.call_args_list[1].kwargs["deduplication_key"],
            )


class TestBusinessPolicyRetriever(unittest.TestCase):
    def test_returns_database_policy_records(self):
        record = SimpleNamespace(
            policy_key="automatic_quote_dispatch",
            title="Automatic dispatch limits",
            category="quote_automation",
            description="Advisory limits.",
            policy_data={"max_auto_approve_value": 25000},
        )
        session = MagicMock()
        session.scalars.return_value.all.return_value = [record]
        session_factory = MagicMock()
        session_factory.return_value.__enter__.return_value = session

        policies = retrieve_active_business_policies(session_factory)

        self.assertEqual(policies[0]["policy_key"], "automatic_quote_dispatch")
        self.assertEqual(policies[0]["policy_data"]["max_auto_approve_value"], 25000)

    def test_fails_closed_when_no_active_policy_is_returned(self):
        session = MagicMock()
        session.scalars.return_value.all.return_value = []
        session_factory = MagicMock()
        session_factory.return_value.__enter__.return_value = session

        with self.assertRaisesRegex(BusinessPolicyRetrievalError, "No active business policies"):
            retrieve_active_business_policies(session_factory)


class TestDspyEmailPrograms(unittest.TestCase):
    def test_synthetic_examples_validate_for_each_registered_task(self):
        examples = load_training_data()

        self.assertEqual(set(examples), set(SIGNATURES))
        self.assertTrue(all(len(task_examples) >= 2 for task_examples in examples.values()))

    def test_policy_evaluation_returns_validated_advisory(self):
        engine_holder = {}
        expected_recommendation = {
            "decision": "review",
            "rationale": "The case requires the backend policy gate to determine eligibility.",
            "policy_keys": ["automatic_quote_dispatch"],
            "missing_evidence": [],
            "confidence": 0.9,
        }

        class FakePredictor:
            def __init__(self, signature):
                self.signature = signature
                self.demos = []

            def __call__(self, **_inputs):
                engine_holder["engine"].last_response = LLMResponse(
                    provider="openai",
                    model="test-model",
                    text="{}",
                    raw={"usage": {"prompt_tokens": 10, "completion_tokens": 4}},
                )
                return SimpleNamespace(structured_result=expected_recommendation)

        def fake_lm(*_args, **kwargs):
            engine_holder["engine"] = kwargs["engine"]
            return object()

        empty_examples = {task: () for task in SIGNATURES}
        router = LLMRouter(providers={"test": object()})
        request = LLMRequest(
            task="policy_evaluation",
            system_prompt="Evaluate the supplied quote case.",
            user_prompt='{"total_amount":8000}',
        )
        with (
            patch("services.dspy_email_programs.retrieve_active_business_policies", return_value=[
                {
                    "policy_key": "automatic_quote_dispatch",
                    "category": "quote_automation",
                    "policy_data": {},
                },
            ]),
            patch("services.dspy_email_programs.load_training_data", return_value=empty_examples),
            patch("services.dspy_email_programs.dspy.LM", side_effect=fake_lm),
            patch("services.dspy_email_programs.dspy.Predict", side_effect=FakePredictor),
            patch("services.dspy_email_programs.dspy.context", return_value=nullcontext()),
            patch("services.dspy_email_programs.dspy.JSONAdapter", return_value=object()),
        ):
            result, response = predict_structured(
                router,
                request,
                PolicyEvaluationRecommendation,
            )

        self.assertEqual(result["decision"], "review")
        self.assertEqual(result["policy_keys"], ["automatic_quote_dispatch"])
        self.assertEqual(response.raw["usage"]["prompt_tokens"], 10)
        self.assertEqual(response.raw["usage"]["completion_tokens"], 4)


if __name__ == "__main__":
    unittest.main()
