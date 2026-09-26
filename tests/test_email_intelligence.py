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
                        "part_number": {"value": "5-89356-42", "source_snippet": "Part No: 5-89356-42"},
                        "quantity": {"value": "2", "source_snippet": "Quantity: 2 EA"},
                        "condition_code": {"value": "AR", "source_snippet": "Condition: AR"},
                        "target_price": {"value": None, "source_snippet": None},
                        "unit_of_measure": {"value": "EA", "source_snippet": "Quantity: 2 EA"},
                        "description": "WINDOW",
                    },
                    {
                        "part_number": {"value": "060-1234-00", "source_snippet": "Part No: 060-1234-00"},
                        "quantity": {"value": "5", "source_snippet": "Quantity: 5 EA"},
                        "condition_code": {"value": "OH", "source_snippet": "Condition: OH"},
                        "target_price": {"value": None, "source_snippet": None},
                        "unit_of_measure": {"value": "EA", "source_snippet": "Quantity: 5 EA"},
                        "description": "ACTUATOR",
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
                "Company: Innovation Aerospace, LLC; Part No: 5-89356-42; Quantity: 2 EA; Condition: AR; "
                "Part No: 060-1234-00; Quantity: 5 EA; Condition: OH",
                task="rfq_extraction",
                router=LLMRouter({"openai": FakeEmailProvider()}),
            )

        self.assertEqual(result.customer_company, "Innovation Aerospace, LLC")
        self.assertEqual([item.part_number.value for item in result.items], ["5-89356-42", "060-1234-00"])
        self.assertEqual([item.quantity.value for item in result.items], ["2", "5"])
        self.assertEqual([item.condition_code.value for item in result.items], ["AR", "OH"])


if __name__ == "__main__":
    unittest.main()
