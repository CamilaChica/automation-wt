import unittest

from services.carrier_tracking_service import CarrierTrackingService
from services.db_service import MockDatabaseService


class TestLocalEndToEnd(unittest.TestCase):
    def test_shipment_webhook_updates_customer_safe_timeline(self):
        service = MockDatabaseService()
        rfq = service.create_rfq(
            "Demo Customer",
            "customer@example.com",
            "Part Number: 060-1234-00 | Qty: 1",
        )
        shipment = service.create_shipment(
            rfq_id=rfq.id,
            quote_id="QTE-DEMO",
            customer_email=rfq.customer_email,
            part_numbers=["060-1234-00"],
            quantity=1,
            public_token="public-demo-token",
        )
        service.update_shipment_tracking(shipment.id, "fedex", "123456789")

        webhook = CarrierTrackingService.normalize_webhook({
            "data": {
                "tracking": {
                    "slug": "fedex",
                    "tracking_number": "123456789",
                    "tag": "InTransit",
                    "checkpoints": [{
                        "location": "Memphis, TN",
                        "message": "Departed carrier facility",
                    }],
                }
            }
        })
        service.add_shipment_event(
            shipment.id,
            webhook["status"],
            webhook["location"],
            webhook["description"],
        )

        public_shipment = service.get_shipment_by_token("public-demo-token")
        public_events = service.get_shipment_events(public_shipment.id)

        self.assertEqual(public_shipment.status, "In Transit")
        self.assertEqual(public_shipment.tracking_number, "123456789")
        self.assertEqual(public_events[-1].location, "Memphis, TN")
        self.assertFalse(hasattr(public_shipment, "supplier_name"))


if __name__ == "__main__":
    unittest.main()
