import unittest

from models.db_models import Quote, QuoteItem
from services.customer_question_service import CustomerQuestionService
from services.inbound_message_classifier import classify_inbound_customer_message
from services.llm_provider import LLMResponse


class _IntentRouter:
    def __init__(self, response: str):
        self.response = response

    def complete(self, request):
        return LLMResponse("mock", "mock-model", self.response, {})


class _UnexpectedRouter:
    def complete(self, request):
        raise AssertionError("Clear quote questions should not require model classification.")


class TestInboundCustomerRouting(unittest.TestCase):
    def test_explicit_po_is_classified_and_number_extracted(self):
        result = classify_inbound_customer_message({
            "subject": "Purchase Order Number: WT-12345",
            "body": "Please find our purchase order attached.",
        }, has_related_quote=True)

        self.assertEqual(result, {"category": "purchase_order", "po_number": "WT-12345"})

    def test_question_is_not_misrouted_as_a_new_rfq(self):
        result = classify_inbound_customer_message({"subject": "Re: quote", "body": "What is the lead time?"}, has_related_quote=True)

        self.assertEqual(result["category"], "client_question")

    def test_grounded_question_answer_uses_only_quote_values(self):
        service = CustomerQuestionService(_IntentRouter('{"requested_fields":["unit_price"],"confidence":0.99}'))
        quote = Quote.model_construct(id="QTE-1", valid_until="2026-10-01", lead_time_days=4)
        item = QuoteItem.model_construct(part_number="060-1234-00", quantity=2, unit_price=125.5, lead_time_days=4)

        answer = service.answer_from_quote("What is the price?", quote, [item])

        self.assertEqual(answer, "Unit Price: 060-1234-00: 125.50 per unit")

    def test_unsupported_question_returns_none_for_review(self):
        service = CustomerQuestionService(_IntentRouter('{"requested_fields":["availability"],"confidence":0.99}'))
        quote = Quote.model_construct(id="QTE-1", valid_until=None, lead_time_days=None)

        self.assertIsNone(service.answer_from_quote("Is it in stock?", quote, []))

    def test_warranty_and_trace_answers_are_deterministic_and_quote_grounded(self):
        service = CustomerQuestionService(_UnexpectedRouter())
        quote = Quote.model_construct(id="QTE-1", valid_until="2026-10-01", lead_time_days=4)
        item = QuoteItem.model_construct(
            part_number="060-1234-00",
            quantity=2,
            certificate_type="FAA 8130-3",
            warranty_terms="12 months",
            trace_documents=["FAA 8130-3 release"],
        )

        answer = service.answer_from_quote(
            "What warranty applies, and what trace documents are recorded?",
            quote,
            [item],
        )

        self.assertIn("Warranty: 060-1234-00: 12 months", answer)
        self.assertIn("Trace: 060-1234-00: FAA 8130-3 release", answer)

    def test_document_request_is_reported_only_when_verified_document_is_selected(self):
        service = CustomerQuestionService(_UnexpectedRouter())
        quote = Quote.model_construct(id="QTE-1", valid_until=None, lead_time_days=None)
        item = QuoteItem.model_construct(
            part_number="060-1234-00",
            quantity=1,
            certificate_type="FAA 8130-3",
            trace_documents=["FAA 8130-3 release"],
        )

        self.assertTrue(service.is_document_request("Please send the traceability certificate."))
        self.assertIsNone(service.answer_from_quote(
            "Please send the traceability certificate.", quote, [item]
        ))
        answer = service.answer_from_quote(
            "Please send the traceability certificate.",
            quote,
            [item],
            source_documents=["8130-3.pdf"],
        )
        self.assertIn("Attached: 8130-3.pdf", answer)


if __name__ == "__main__":
    unittest.main()