import os
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.auth import current_user
from api.main import app


class VoiceApiTests(unittest.TestCase):
    staff = {"role": "ROLE_ADMIN", "email": "ops@wingedtycoons.com"}

    def setUp(self):
        app.dependency_overrides[current_user] = lambda: self.staff
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_session_returns_only_the_ephemeral_credential(self):
        openai_response = SimpleNamespace(
            status_code=200,
            json=lambda: {"value": "ephemeral-demo-token"},
        )
        with patch.dict(os.environ, {"OPENAI_API_KEY": "server-only-key"}), patch(
            "api.main.requests.post", return_value=openai_response
        ) as openai_post:
            response = self.client.post("/api/session", json={"language": "fr"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "client_secret": "ephemeral-demo-token",
            "model": "gpt-realtime-2",
        })
        self.assertNotIn("server-only-key", response.text)
        self.assertEqual(openai_post.call_args.args[0], "https://api.openai.com/v1/realtime/client_secrets")
        session = openai_post.call_args.kwargs["json"]["session"]
        self.assertEqual(session["audio"]["input"]["transcription"]["language"], "fr")
        self.assertEqual(session["audio"]["output"]["voice"], "marin")
        self.assertIn("You are Camila", session["instructions"])

    def test_customer_can_use_inventory_tools_but_not_operations_dashboard(self):
        app.dependency_overrides[current_user] = lambda: {"role": "ROLE_CUSTOMER", "email": "buyer@example.com"}
        inventory = self.client.post(
            "/api/voice/tools/check_inventory_availability",
            json={"part_number": "060-1234-00"},
        )
        dashboard = self.client.get("/api/voice/dashboard")

        self.assertEqual(inventory.status_code, 200)
        self.assertEqual(inventory.json()["matches"][0]["unit_price"], 4250.0)
        self.assertEqual(dashboard.status_code, 403)

    def test_customer_session_uses_configured_custom_voice(self):
        openai_response = SimpleNamespace(status_code=200, json=lambda: {"value": "customer-ephemeral-token"})
        app.dependency_overrides[current_user] = lambda: {"role": "ROLE_CUSTOMER", "email": "buyer@example.com"}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "server-only-key", "OPENAI_REALTIME_VOICE_ID": "voice_camila"}), patch(
            "api.main.requests.post", return_value=openai_response
        ) as openai_post:
            response = self.client.post("/api/session", json={"language": "es"})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("server-only-key", response.text)
        request_body = openai_post.call_args.kwargs["json"]
        self.assertEqual(request_body["session"]["audio"]["output"]["voice"], {"id": "voice_camila"})
        self.assertEqual(request_body["session"]["audio"]["input"]["transcription"]["language"], "es")

    def test_rejected_custom_voice_retries_with_builtin_and_returns_secret(self):
        unavailable_voice = SimpleNamespace(status_code=404, text="Custom voice not found")
        valid_session = SimpleNamespace(status_code=200, text="", json=lambda: {"value": "fallback-ephemeral-token"})
        requests_seen = []

        def capture_request(*args, **kwargs):
            requests_seen.append(copy.deepcopy(kwargs["json"]))
            return unavailable_voice if len(requests_seen) == 1 else valid_session

        with patch.dict(os.environ, {"OPENAI_API_KEY": "server-only-key", "OPENAI_REALTIME_VOICE_ID": "voice_unavailable"}), patch(
            "api.main.requests.post", side_effect=capture_request
        ) as openai_post:
            response = self.client.post("/api/session", json={"language": "en"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["client_secret"], "fallback-ephemeral-token")
        self.assertEqual(openai_post.call_count, 2)
        self.assertEqual(requests_seen[0]["session"]["audio"]["output"]["voice"], {"id": "voice_unavailable"})
        self.assertEqual(requests_seen[1]["session"]["audio"]["output"]["voice"], "marin")

    def test_customer_order_lookup_only_returns_their_own_rfq(self):
        own_rfq = SimpleNamespace(id="WT-OWN", customer_email="buyer@example.com", status="Quoted", part_number="060-1234-00")
        other_rfq = SimpleNamespace(id="WT-OTHER", customer_email="other@example.com", status="Quoted", part_number="10-60539-1")
        app.dependency_overrides[current_user] = lambda: {"role": "ROLE_CUSTOMER", "email": "buyer@example.com"}
        with patch("api.main.db_service.list_rfqs", return_value=[own_rfq, other_rfq]):
            own = self.client.post("/api/voice/tools/get_order_status", json={"rfq_or_order_id": "WT-OWN"})
            other = self.client.post("/api/voice/tools/get_order_status", json={"rfq_or_order_id": "WT-OTHER"})

        self.assertTrue(own.json()["found"])
        self.assertEqual(own.json()["part_number"], "060-1234-00")
        self.assertFalse(other.json()["found"])


if __name__ == "__main__":
    unittest.main()