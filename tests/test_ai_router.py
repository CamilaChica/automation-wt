import unittest
from unittest.mock import patch

from services.ai_router import AIRouter, ProviderCallError


class TestAIRouterRouting(unittest.TestCase):
    def setUp(self):
        self.router = AIRouter(openai_key=None, anthropic_key=None, gemini_key=None)

    def test_parse_rfq_uses_gemini_primary(self):
        with patch.object(AIRouter, "_call_provider", return_value={"supplier_email": "quotes@test.com"}) as mock_call:
            out = self.router.parse_rfq("sample rfq text")
            self.assertEqual(mock_call.call_args[0][1], "gemini")
            self.assertEqual(out["provider"], "gemini")
            self.assertFalse(out["fallback_used"])
            self.assertIn("supplier_email", out["result"])

    def test_fallback_order_on_failure(self):
        calls = []
        def side_effect(action, provider, payload):
            del action
            del payload
            calls.append(provider)
            if provider == "gemini":
                raise ProviderCallError("gemini failed")
            return {"status": f"ok-{provider}"}

        with patch.object(AIRouter, "_call_provider", side_effect=side_effect):
            out = self.router.parse_rfq("some rfq")
            self.assertGreaterEqual(len(calls), 2)
            self.assertEqual(calls[0], "gemini")
            self.assertEqual(out["provider"], "openai")
            self.assertTrue(out["fallback_used"])
            self.assertEqual(out["result"]["status"], "ok-openai")

    def test_draft_sales_email_primary_openai(self):
        with patch.object(AIRouter, "_call_provider", return_value={"subject": "Hi", "body": "email body"}) as mock_call:
            out = self.router.draft_sales_email({"price": 100})
            self.assertEqual(mock_call.call_args[0][1], "openai")
            self.assertEqual(out["provider"], "openai")
            self.assertEqual(out["result"]["body"], "email body")
            self.assertEqual(out["model"], "gpt-4o")

if __name__ == "__main__":
    unittest.main()
