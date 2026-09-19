import base64
import hashlib
import hmac
import json
import os
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient


class TestCarrierWebhookRoute(unittest.TestCase):
    def test_signed_aftership_webhook_updates_matching_shipment(self):
        with patch.dict(os.environ, {"CARRIER_WEBHOOK_SECRET": "route-secret"}, clear=False):
            from api.main import app
            from services.db_service import db_service

            tracking_number = f"LOCAL-TEST-{uuid.uuid4().hex[:8]}"
            rfq = db_service.create_rfq("Webhook Customer", "webhook@example.com", "Part Number: WEBHOOK-1 | Qty: 1")
            shipment = db_service.create_shipment(
                rfq_id=rfq.id,
                quote_id="QTE-WEBHOOK",
                customer_email=rfq.customer_email,
                part_numbers=["WEBHOOK-1"],
                quantity=1,
                public_token="webhook-token",
            )
            db_service.update_shipment_tracking(shipment.id, "fedex", tracking_number)
            payload = {
                "event": "tracking_update",
                "msg": {
                    "slug": "fedex",
                    "tracking_number": tracking_number,
                    "tag": "InTransit",
                    "checkpoints": [{"location": "Memphis, TN", "message": "Departed carrier facility"}],
                },
            }
            body = json.dumps(payload, separators=(",", ":")).encode()
            signature = base64.b64encode(hmac.new(b"route-secret", body, hashlib.sha256).digest()).decode()

            response = TestClient(app).post(
                "/api/webhooks/carriers/aftership",
                content=body,
                headers={"aftership-hmac-sha256": signature, "Content-Type": "application/json"},
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json().get("shipment_id"), shipment.id, response.text)
            self.assertEqual(db_service.get_shipment(shipment.id).status, "In Transit")


if __name__ == "__main__":
    unittest.main()
