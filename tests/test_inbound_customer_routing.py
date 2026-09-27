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


if __name__ == "__main__":
    unittest.main()