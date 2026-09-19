import hashlib
import hmac
import base64
import json
import unittest

from services.carrier_tracking_service import CarrierTrackingService


class TestCarrierTrackingService(unittest.TestCase):
    def test_normalizes_carrier_statuses(self):
        payload = {
            "data": {
                "tracking": {
                    "slug": "fedex",
                    "tracking_number": "123456789",
                    "tag": "OutForDelivery",
                    "checkpoints": [{"location": "Miami, FL", "message": "On vehicle for delivery"}],
                }
            }
        }

        result = CarrierTrackingService.normalize_webhook(payload)

        self.assertEqual(result["carrier"], "fedex")
        self.assertEqual(result["tracking_number"], "123456789")
        self.assertEqual(result["status"], "Out for Delivery")
        self.assertEqual(result["location"], "Miami, FL")

    def test_verifies_signed_webhook(self):
        body = json.dumps({"event": "tracking_update"}).encode()
        secret = "webhook-secret"
        signature = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()

        self.assertTrue(CarrierTrackingService.verify_webhook(body, signature, secret))
        self.assertFalse(CarrierTrackingService.verify_webhook(body, "bad-signature", secret))
        self.assertFalse(CarrierTrackingService.verify_webhook(body, signature, ""))

    def test_tracker_without_key_is_explicit_dry_run(self):
        result = CarrierTrackingService(api_key="").create_tracker("usps", "9400111899223856928491")

        self.assertEqual(result["status"], "DRY_RUN")
        self.assertEqual(result["carrier"], "usps")


if __name__ == "__main__":
    unittest.main()
