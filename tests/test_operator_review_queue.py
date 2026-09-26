import asyncio
import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api.auth import current_user
from api.main import app
from services.orchestration_service import OrchestrationService
from services.operations_store import OperationsStore


class OperatorReviewQueueTests(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def test_review_repository_persists_source_hypotheses_and_atomic_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OperationsStore(Path(directory) / "operations.db")
            extraction = {
                "items": [{
                    "part_number": {"value": "060-1234-00", "source_snippet": "Part Number: 060-1234-00"},
                    "resolution_hypotheses": [{"field": "quantity", "candidate_value": "2 or 3", "source_snippets": ["Qty: 2", "Qty: 3"]}],
                }],
            }
            review_id = store.enqueue_operator_review(
                idempotency_key="review-test-1",
                task="supplier_quote_extraction",
                source_text="Part Number: 060-1234-00; Qty: 2 or 3",
                extraction=extraction,
                reason="conflicting_quantity",
                prompt_version="supplier-quote-v1",
                hold_flags=["quantity"],
            )

            record = store.get_operator_review(review_id)
            self.assertEqual(record["source_text"], "Part Number: 060-1234-00; Qty: 2 or 3")
            self.assertEqual(record["extraction"]["items"][0]["part_number"]["source_snippet"], "Part Number: 060-1234-00")
            self.assertEqual(record["extraction"]["items"][0]["resolution_hypotheses"][0]["field"], "quantity")
            self.assertEqual(len(store.list_operator_reviews()), 1)
            self.assertEqual(record["prompt_version"], "supplier-quote-v1")
            store.record_llm_telemetry(
                task="supplier_quote_extraction",
                prompt_version="supplier-quote-v1",
                model_id="gpt-4o",
                model_calls=["gpt-4o-mini", "gpt-4o"],
                latency_ms=130.5,
                input_tokens=210,
                output_tokens=65,
                estimated_cost_usd=0.0009,
                validation_result="VALIDATED",
                review_queue_id=review_id,
            )
            self.assertTrue(store.claim_operator_review_decision(review_id, "APPROVE", "operator@example.test", {"comments": "verified"}))
            self.assertFalse(store.claim_operator_review_decision(review_id, "REJECT", "other@example.test", {}))
            store.complete_operator_review_decision(review_id, status="APPROVED")
            self.assertEqual(store.get_operator_review(review_id)["status"], "APPROVED")
            telemetry = store.list_llm_telemetry(task="supplier_quote_extraction")[0]
            self.assertEqual(telemetry["prompt_version"], "supplier-quote-v1")
            self.assertEqual(telemetry["model_calls"], ["gpt-4o-mini", "gpt-4o"])
            self.assertEqual(telemetry["input_tokens"], 210)
            self.assertEqual(telemetry["output_tokens"], 65)
            self.assertEqual(telemetry["operator_review_outcome"], "APPROVED")

    def test_orchestration_owns_rfq_review_transition_and_resumes_without_model_call(self):
        source = "Company: Example Maintenance; Part Number: 060-1234-00; Quantity: 2 EA; Condition: NE"
        review = {
            "id": "REV-SERVICE-1",
            "task": "rfq_extraction",
            "entity_id": "RFQ-SERVICE-1",
            "source_text": source,
            "status": "PENDING",
            "extraction": {
                "email_type": "customer_rfq",
                "customer_name": "Buyer",
                "customer_company": "Example Maintenance",
                "customer_email": "buyer@example.test",
                "items": [{
                    "part_number": {"value": "060-1234-00", "source_snippet": "Part Number: 060-1234-00"},
                    "quantity": {"value": "2", "source_snippet": "Quantity: 2 EA"},
                    "condition_code": {"value": "NE", "source_snippet": "Condition: NE"},
                    "target_price": {"value": None, "source_snippet": None},
                    "lead_time_days": {"value": None, "source_snippet": None},
                    "unit_of_measure": {"value": "EA", "source_snippet": "Quantity: 2 EA"},
                    "currency": {"value": None, "source_snippet": None},
                    "trace_documents": [],
                    "missing_fields": [],
                    "needs_escalation": True,
                    "escalation_reason": "low_extraction_confidence",
                    "resolution_hypotheses": [],
                }],
                "missing_fields": [],
                "confidence_score": 0.94,
                "needs_escalation": True,
                "escalation_reason": "low_extraction_confidence",
            },
        }
        rfq = SimpleNamespace(
            id="RFQ-SERVICE-1",
            status="Pending_Internal_Review",
            customer_name="Buyer",
            customer_email="buyer@example.test",
        )
        service = OrchestrationService()
        service.process_rfq_pipeline = AsyncMock(return_value={"status": "Supplier_Request_Sent"})
        with (
            patch("services.orchestration_service.operations_store.claim_operator_review_decision", return_value=True),
            patch("services.orchestration_service.operations_store.complete_operator_review_decision") as complete,
            patch("services.orchestration_service.db_service.get_rfq", return_value=rfq),
            patch("services.orchestration_service.db_service.update_rfq_customer"),
            patch("services.orchestration_service.db_service.replace_rfq_items") as replace_items,
            patch("services.orchestration_service.db_service.update_rfq_status") as update_status,
            patch("services.orchestration_service.db_service.add_audit_log"),
            patch("services.email_intelligence.extract_email_intelligence", side_effect=AssertionError("must not rerun extraction")),
        ):
            result = asyncio.run(service.decide_extraction_review(
                review=review,
                decision="approve",
                operator="operator@example.test",
            ))

        self.assertEqual(result["status"], "APPROVED")
        replace_items.assert_called_once_with("RFQ-SERVICE-1", [{
            "part_number": "060-1234-00",
            "quantity": 2,
            "condition_code": "NE",
            "unit_of_measure": "EA",
        }])
        update_status.assert_called_once_with("RFQ-SERVICE-1", "Validating")
        complete.assert_called_once_with("REV-SERVICE-1", status="APPROVED")
        service.process_rfq_pipeline.assert_awaited_once_with("RFQ-SERVICE-1")

    def test_operator_api_exposes_evidence_and_denies_customer(self):
        review = {
            "id": "REV-API-1",
            "task": "supplier_quote_extraction",
            "entity_id": "email-1",
            "source_text": "Part Number: 060-1234-00",
            "extraction": {"items": [{"part_number": {"value": "060-1234-00", "source_snippet": "Part Number: 060-1234-00"}}]},
            "hold_flags": ["trace_documents"],
            "status": "PENDING",
        }
        with (
            patch("api.main.operations_store.list_operator_reviews", return_value=[review]),
            patch("api.main.operations_store.get_operator_review", return_value=review),
        ):
            app.dependency_overrides[current_user] = lambda: {"role": "ROLE_ADMIN", "email": "ops@example.test"}
            client = TestClient(app)
            listed = client.get("/api/internal/extraction-reviews")
            detail = client.get("/api/internal/extraction-reviews/REV-API-1")
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["extraction"]["items"][0]["part_number"]["source_snippet"], "Part Number: 060-1234-00")
            self.assertEqual(detail.json()["source_text"], review["source_text"])

        app.dependency_overrides[current_user] = lambda: {"role": "ROLE_CUSTOMER", "email": "buyer@example.test"}
        denied = TestClient(app).get("/api/internal/extraction-reviews")
        self.assertEqual(denied.status_code, 403)

    def test_supplier_approval_consumes_saved_extraction_without_reextracting(self):
        source = (
            "From: quotes@example.test\n"
            "Part Number: 060-1234-00\nQuantity: 2 EA\nCondition: NE\n"
            "Unit price: $125 USD\nLead time: 5 days\nFAA 8130-3 certificate included."
        )
        extraction = {
            "email_type": "supplier_quote",
            "supplier_name": "Example Supplier",
            "supplier_email": "quotes@example.test",
            "items": [{
                "part_number": {"value": "060-1234-00", "source_snippet": "Part Number: 060-1234-00"},
                "quantity": {"value": "2", "source_snippet": "Quantity: 2 EA"},
                "condition_code": {"value": "NE", "source_snippet": "Condition: NE"},
                "target_price": {"value": "125", "source_snippet": "Unit price: $125 USD"},
                "lead_time_days": {"value": "5 days", "source_snippet": "Lead time: 5 days"},
                "unit_of_measure": {"value": "EA", "source_snippet": "Quantity: 2 EA"},
                "currency": {"value": "USD", "source_snippet": "Unit price: $125 USD"},
                "trace_documents": ["FAA 8130-3"],
                "missing_fields": [],
                "needs_escalation": True,
                "escalation_reason": "low_confidence",
                "resolution_hypotheses": [],
            }],
            "missing_fields": [],
            "confidence_score": 0.93,
        }
        review = {"id": "REV-APPROVE-1", "task": "supplier_quote_extraction", "entity_id": "EMAIL-1", "source_text": source, "extraction": extraction, "status": "PENDING"}
        app.dependency_overrides[current_user] = lambda: {"role": "ROLE_PURCHASING", "email": "buyer-ops@example.test"}
        with (
            patch("api.main.operations_store.get_operator_review", return_value=review),
            patch("api.main.orchestration_service.decide_extraction_review", new_callable=AsyncMock, return_value={"review_id": "REV-APPROVE-1", "status": "APPROVED", "offers": [{"id": "SPO-1"}]}) as decide,
            patch("services.email_intelligence.extract_email_intelligence", side_effect=AssertionError("LLM must not run during approval")),
        ):
            response = TestClient(app).post(
                "/api/internal/extraction-reviews/REV-APPROVE-1/decision",
                json={"decision": "approve"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "APPROVED")
        decide.assert_awaited_once()
        self.assertEqual(decide.call_args.kwargs["decision"], "approve")
        self.assertEqual(decide.call_args.kwargs["approved_extraction"], None)

    def test_rfq_approval_transitions_to_validation_without_llm_reexecution(self):
        source = "Company: Example Maintenance; Part Number: 060-1234-00; Quantity: 2 EA; Condition: NE"
        extraction = {
            "email_type": "customer_rfq",
            "customer_name": "Buyer One",
            "customer_company": "Example Maintenance",
            "customer_email": "buyer@example.test",
            "items": [{
                "part_number": {"value": "060-1234-00", "source_snippet": "Part Number: 060-1234-00"},
                "quantity": {"value": "2", "source_snippet": "Quantity: 2 EA"},
                "condition_code": {"value": "NE", "source_snippet": "Condition: NE"},
                "target_price": {"value": None, "source_snippet": None},
                "lead_time_days": {"value": None, "source_snippet": None},
                "unit_of_measure": {"value": "EA", "source_snippet": "Quantity: 2 EA"},
                "currency": {"value": None, "source_snippet": None},
                "trace_documents": [],
                "missing_fields": [],
                "needs_escalation": True,
                "escalation_reason": "low_extraction_confidence",
                "resolution_hypotheses": [],
            }],
            "missing_fields": [],
            "confidence_score": 0.94,
            "needs_escalation": True,
            "escalation_reason": "low_extraction_confidence",
        }
        review = {"id": "REV-RFQ-1", "task": "rfq_extraction", "entity_id": "RFQ-REVIEW-1", "source_text": source, "extraction": extraction, "status": "PENDING"}
        rfq = SimpleNamespace(id="RFQ-REVIEW-1", status="Pending_Internal_Review", customer_name="Buyer One", customer_email="buyer@example.test")
        app.dependency_overrides[current_user] = lambda: {"role": "ROLE_SALES", "email": "sales-ops@example.test"}
        with (
            patch("api.main.operations_store.get_operator_review", return_value=review),
            patch("api.main.orchestration_service.decide_extraction_review", new_callable=AsyncMock, return_value={"review_id": "REV-RFQ-1", "status": "APPROVED", "rfq_id": "RFQ-REVIEW-1", "pipeline": {"status": "Supplier_Request_Sent"}}) as decide,
            patch("services.email_intelligence.extract_email_intelligence", side_effect=AssertionError("approval must not re-extract")),
        ):
            response = TestClient(app).post(
                "/api/internal/extraction-reviews/REV-RFQ-1/decision",
                json={"decision": "approve"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["pipeline"]["status"], "Supplier_Request_Sent")
        decide.assert_awaited_once()
        self.assertEqual(decide.call_args.kwargs["decision"], "approve")

    def test_operator_can_reject_a_pending_extraction(self):
        review = {"id": "REV-REJECT-1", "task": "supplier_quote_extraction", "entity_id": "EMAIL-REJECT-1", "status": "PENDING", "extraction": {}, "source_text": ""}
        app.dependency_overrides[current_user] = lambda: {"role": "ROLE_PURCHASING", "email": "buyer-ops@example.test"}
        with (
            patch("api.main.operations_store.get_operator_review", return_value=review),
            patch("api.main.orchestration_service.decide_extraction_review", new_callable=AsyncMock, return_value={"review_id": "REV-REJECT-1", "status": "REJECTED"}) as decide,
        ):
            response = TestClient(app).post(
                "/api/internal/extraction-reviews/REV-REJECT-1/decision",
                json={"decision": "reject", "comments": "The source document does not support the extracted value."},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "REJECTED")
        decide.assert_awaited_once()
        self.assertEqual(decide.call_args.kwargs["decision"], "reject")


if __name__ == "__main__":
    unittest.main()
