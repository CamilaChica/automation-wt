import os
import unittest
from unittest.mock import patch

from services.twilio_service import TwilioService


class TestTwilioService(unittest.TestCase):
    def test_defaults_to_dry_run_without_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            result = TwilioService().send_sms("+13055550142", "Shipment update")

        self.assertEqual(result["status"], "DRY_RUN")
        self.assertEqual(result["provider"], "twilio")

    def test_rejects_non_e164_recipient(self):
        with self.assertRaises(ValueError):
            TwilioService().send_sms("305-555-0142", "Shipment update")

    @patch("services.twilio_service.requests.post")
    def test_enabled_twilio_sends_authenticated_request(self, mock_post):
        mock_post.return_value.json.return_value = {"sid": "SM-123"}
        mock_post.return_value.raise_for_status.return_value = None
        environment = {
            "TWILIO_ENABLED": "true",
            "TWILIO_ACCOUNT_SID": "AC-123",
            "TWILIO_AUTH_TOKEN": "secret",
            "TWILIO_FROM_NUMBER": "+13055550142",
        }
        with patch.dict(os.environ, environment, clear=True):
            result = TwilioService().send_sms("+13055550143", "Shipment update")

        self.assertEqual(result["status"], "SENT")
        self.assertEqual(result["message_id"], "SM-123")
        self.assertEqual(mock_post.call_args.kwargs["auth"], ("AC-123", "secret"))


if __name__ == "__main__":
    unittest.main()
