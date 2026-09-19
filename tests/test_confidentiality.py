import unittest

from services.communication_service import CommunicationService


class TestCommunicationConfidentiality(unittest.TestCase):
    def test_internal_purchase_order_notice_contains_supplier_details(self):
        result = CommunicationService().notify_purchase_order(
            recipient="camila@wingedtycoons.com",
            po_number="PO-100",
            customer_name="Customer Company",
            customer_email="buyer@example.com",
            quote_id="QTE-100",
            items=[{
                "part_number": "060-1234-00",
                "quantity": 1,
                "unit_price": 1500.0,
                "supplier_name": "Apex Aerospace",
                "supplier_unit_cost": 1100.0,
            }],
        )

        self.assertIn("Apex Aerospace", result["body"])
        self.assertIn("buyer@example.com", result["body"])

    def test_supplier_confirmation_contains_no_customer_identity_or_price(self):
        result = CommunicationService().request_supplier_availability_confirmation(
            recipient="quotes@supplier.example",
            supplier_name="Apex Aerospace",
            po_number="PO-100",
            items=[{
                "part_number": "060-1234-00",
                "quantity": 1,
                "supplier_unit_cost": 1100.0,
            }],
        )

        self.assertNotIn("Customer Company", result["body"])
        self.assertNotIn("buyer@example.com", result["body"])
        self.assertNotIn("1500", result["body"])
        self.assertIn("available", result["body"].lower())

    def test_customer_tracking_message_contains_no_supplier_data(self):
        result = CommunicationService().send_shipment_tracking_link(
            recipient="buyer@example.com",
            shipment_id="SHP-100",
            public_token="private-token",
        )

        self.assertIn("private-token", result["body"])
        self.assertNotIn("supplier", result["body"].lower())
        self.assertNotIn("margin", result["body"].lower())


if __name__ == "__main__":
    unittest.main()
