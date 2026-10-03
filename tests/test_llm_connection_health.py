import os
import unittest
from unittest.mock import Mock, patch

import requests
from fastapi.testclient import TestClient

from api.auth import current_user
from api.main import app
from services.llm_provider import LLMResponse


class TestLLMConnectionHealth(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[current_user] = lambda: {
            "role": "ROLE_ADMIN",
            "email": "admin@example.com",
        }
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_live_llm_connection_test_calls_every_configured_provider(self):
        providers = {
            "OpenAIProvider": Mock(),
            "AnthropicProvider": Mock(),
            "GeminiProvider": Mock(),
        }
        for name, provider in providers.items():
            provider.return_value.complete.return_value = LLMResponse(
                name.removesuffix("Provider").lower(),
                "test-model",
                "OK",
                {},
            )

        with (
            patch.dict(os.environ, {
                "OPENAI_API_KEY": "test-openai-key",
                "ANTHROPIC_API_KEY": "test-anthropic-key",
                "GEMINI_API_KEY": "test-gemini-key",
            }),
            patch("api.main.OpenAIProvider", providers["OpenAIProvider"]),
            patch("api.main.AnthropicProvider", providers["AnthropicProvider"]),
            patch("api.main.GeminiProvider", providers["GeminiProvider"]),
        ):
            response = self.client.post("/api/internal/llm/test-connections")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([result["status"] for result in response.json()["results"]], ["connected"] * 3)
        for provider in providers.values():
            provider.return_value.complete.assert_called_once()
            request = provider.return_value.complete.call_args.args[0]
            self.assertEqual(request.task, "connectivity_test")
            self.assertEqual(request.user_prompt, "Reply OK.")
            self.assertEqual(request.max_tokens, 8)
            self.assertEqual(request.response_format, "text")
        self.assertNotIn("test-openai-key", response.text)
        self.assertNotIn("test-anthropic-key", response.text)
        self.assertNotIn("test-gemini-key", response.text)

    def test_live_llm_connection_test_reports_missing_keys_without_provider_calls(self):
        with (
            patch.dict(os.environ, {
                "OPENAI_API_KEY": "",
                "ANTHROPIC_API_KEY": "",
                "GEMINI_API_KEY": "",
            }),
            patch("api.main.OpenAIProvider") as openai,
            patch("api.main.AnthropicProvider") as anthropic,
            patch("api.main.GeminiProvider") as gemini,
        ):
            response = self.client.post("/api/internal/llm/test-connections")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([result["status"] for result in response.json()["results"]], ["not_configured"] * 3)
        openai.assert_not_called()
        anthropic.assert_not_called()
        gemini.assert_not_called()

    def test_live_llm_connection_test_sanitizes_provider_auth_errors(self):
        response_with_status = requests.Response()
        response_with_status.status_code = 401
        failure = requests.HTTPError("request included must-not-leak", response=response_with_status)

        with (
            patch.dict(os.environ, {
                "OPENAI_API_KEY": "must-not-leak",
                "ANTHROPIC_API_KEY": "",
                "GEMINI_API_KEY": "",
            }),
            patch("api.main.OpenAIProvider") as openai,
            patch("api.main.AnthropicProvider"),
            patch("api.main.GeminiProvider"),
        ):
            openai.return_value.complete.side_effect = failure
            response = self.client.post("/api/internal/llm/test-connections")

        self.assertEqual(response.status_code, 200)
        result = response.json()["results"][0]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["message"], "The provider rejected the credentials or model access.")
        self.assertNotIn("must-not-leak", response.text)

    def test_live_llm_connection_test_requires_authentication(self):
        app.dependency_overrides.clear()
        response = TestClient(app).post("/api/internal/llm/test-connections")

        self.assertEqual(response.status_code, 401)
