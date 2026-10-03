import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.auth import current_user
from api.main import app
from services.async_database import get_async_db
from tools.registry import ToolAuthorizationError, ToolConfirmationRequired
from tools.voice_tools import VOICE_TOOL_REGISTRY


class VoiceToolRegistryTests(unittest.TestCase):
    def test_realtime_definitions_are_generated_from_allowlisted_schemas(self):
        definitions = VOICE_TOOL_REGISTRY.realtime_definitions()

        self.assertEqual(
            [definition["name"] for definition in definitions],
            [
                "check_inventory_availability",
                "get_order_status",
                "log_customer_concern",
            ],
        )
        concern_schema = definitions[-1]["parameters"]
        self.assertEqual(
            set(concern_schema["required"]),
            {"issue_type", "details", "part_number"},
        )
        self.assertFalse(concern_schema["additionalProperties"])

    def test_concern_tool_requires_role_and_human_confirmation(self):
        arguments = {
            "issue_type": "quote_follow_up",
            "details": "Please have an operator follow up.",
            "part_number": "060-1234-00",
        }

        with self.assertRaises(ToolAuthorizationError):
            VOICE_TOOL_REGISTRY.validate_call(
                "log_customer_concern",
                arguments,
                role="ROLE_GUEST",
                human_confirmed=True,
            )
        with self.assertRaises(ToolConfirmationRequired):
            VOICE_TOOL_REGISTRY.validate_call(
                "log_customer_concern",
                arguments,
                role="ROLE_CUSTOMER",
            )

        validated = VOICE_TOOL_REGISTRY.validate_call(
            "log_customer_concern",
            arguments,
            role="ROLE_CUSTOMER",
            human_confirmed=True,
        )
        self.assertEqual(validated, arguments)


class VoiceToolEndpointTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[current_user] = lambda: {
            "role": "ROLE_ADMIN",
            "email": "ops@wingedtycoons.com",
        }
        app.dependency_overrides[get_async_db] = lambda: None
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_concern_is_not_recorded_without_separate_confirmation_header(self):
        with patch("api.main.log_customer_concern") as log_concern:
            response = self.client.post(
                "/api/voice/tools/log_customer_concern",
                json={
                    "issue_type": "quote_follow_up",
                    "details": "Please have an operator follow up.",
                    "part_number": "060-1234-00",
                },
            )

        self.assertEqual(response.status_code, 428)
        log_concern.assert_not_called()

    def test_concern_is_recorded_only_after_confirmed_call(self):
        expected = {"logged": True, "requires_review": False, "concern": {}}
        with patch("api.main.log_customer_concern", return_value=expected) as log_concern:
            response = self.client.post(
                "/api/voice/tools/log_customer_concern",
                headers={"X-Human-Confirmed": "true"},
                json={
                    "issue_type": "quote_follow_up",
                    "details": "Please have an operator follow up.",
                    "part_number": "060-1234-00",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        log_concern.assert_called_once_with(
            "quote_follow_up",
            "Please have an operator follow up.",
            "060-1234-00",
            "",
        )


if __name__ == "__main__":
    unittest.main()
