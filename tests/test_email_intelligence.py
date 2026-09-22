import json
import os
import unittest
from unittest.mock import patch

from services.email_intelligence import extract_email_intelligence
from services.llm_provider import LLMProvider, LLMResponse, LLMRouter


class FakeEmailProvider(LLMProvider):
    name = "openai"

    def complete(self, request):
        return LLMResponse(
            provider=self.name,
            model="test-model",
            text=json.dumps({
                "email_type": "customer_rfq",
                "customer_name": "Sandy Delgado",
                "customer_company": "Innovation Aerospace, LLC",
                "customer_email": "sales@innovation-aero.com",
                "supplier_name": None,
                "supplier_email": None,
                "items": [
                    {
                        "part_number": "5-89356-42",
                        "description": "WINDOW",
                        "quantity": 2,
                        "condition_code": "AR",
                        "unit_price": None,
                        "currency": "USD",
                        "lead_time_days": None,
                        "availability_location": None,
                        "warranty_terms": None,
                        "trace_documents": [],
                    },
                    {
                        "part_number": "060-1234-00",
                        "description": "ACTUATOR",
                        "quantity": 5,
                        "condition_code": "OH",
                        "unit_price": None,
                        "currency": "USD",
                        "lead_time_days": None,
                        "availability_location": None,
                        "warranty_terms": None,
                        "trace_documents": [],
                    },
                ],
                "missing_fields": [],
                "confidence_score": 0.97,
            }),
            raw={},
        )


class EmailIntelligenceTests(unittest.TestCase):
    def test_structured_extraction_preserves_all_line_items_and_identity(self):
        with patch.dict(os.environ, {"LLM_LIVE_ENABLED": "true"}, clear=False):
            result = extract_email_intelligence(
                "PartsBase table email",
                task="rfq_extraction",
                router=LLMRouter({"openai": FakeEmailProvider()}),
            )

        self.assertEqual(result.customer_company, "Innovation Aerospace, LLC")
        self.assertEqual([item.part_number for item in result.items], ["5-89356-42", "060-1234-00"])
        self.assertEqual([item.quantity for item in result.items], [2, 5])
        self.assertEqual([item.condition_code for item in result.items], ["AR", "OH"])


if __name__ == "__main__":
    unittest.main()
