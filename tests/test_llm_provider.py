import os
import unittest
from unittest.mock import patch

from services.llm_provider import LLMRequest, LLMResponse, LLMRouter, OpenAIProvider


class FakeProvider:
    def __init__(self, name):
        self.name = name
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return LLMResponse(self.name, "test-model", f"{self.name}:{request.task}", {})


class TestLLMProvider(unittest.TestCase):
    def test_router_assigns_language_task_to_configured_provider(self):
        openai = FakeProvider("openai")
        anthropic = FakeProvider("anthropic")
        with patch.dict(os.environ, {"LLM_TASK_PROVIDERS": '{"rfq_extraction":"anthropic"}'}, clear=False):
            router = LLMRouter({"openai": openai, "anthropic": anthropic})
            result = router.complete(LLMRequest("rfq_extraction", "system", "user"))

        self.assertEqual(result.provider, "anthropic")
        self.assertEqual(len(anthropic.requests), 1)
        self.assertEqual(len(openai.requests), 0)

    def test_router_rejects_unknown_provider(self):
        with patch.dict(os.environ, {"LLM_TASK_PROVIDERS": '{"rfq_extraction":"unknown"}'}, clear=False):
            router = LLMRouter({"openai": FakeProvider("openai")})
            with self.assertRaises(ValueError):
                router.complete(LLMRequest("rfq_extraction", "system", "user"))

    def test_openai_requires_environment_secret(self):
        with patch.dict(os.environ, {}, clear=True):
            provider = OpenAIProvider()
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                provider.complete(LLMRequest("rfq_extraction", "system", "user"))


if __name__ == "__main__":
    unittest.main()
