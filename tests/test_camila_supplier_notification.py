"""Unit tests verifying that emails triggered to camila@wingedtycoons.com include selected supplier details."""

import os
import unittest
from unittest.mock import patch, MagicMock

from services.communication_service import CommunicationService


class TestCamilaSupplierNotification(unittest.TestCase):
    def test_purchase_order_notification_includes_selected_supplier_details(self):
        service = CommunicationService()
        items = [
            {
                "part_number": "140-810043-12",
                "quantity": 2,
                "unit_price": 4500.0,
                "supplier_name": "Aero Global Spares Inc",
                "supplier_email": "sales@aeroglobalspares.com",
                "supplier_unit_cost": 3200.0,
                "supplier_condition": "FN",
                "supplier_certificate": "FAA 8130-3 Dual Release",
                "supplier_lead_time": "1-2 Days",
                "supplier_location": "Miami, FL",
            }
        ]

        with patch.object(service, "_send") as mock_send:
            mock_send.return_value = {"transmission_status": "DRY_RUN", "communication_id": "COM-CAMILA-1"}
            service.notify_purchase_order(
                recipient="camila@wingedtycoons.com",
                po_number="PO-2026",
                customer_name="Tradex Aviation",
                customer_email="purchase@tasfzc.com",
                quote_id="QTE-9999",
                items=items,
            )

            mock_send.assert_called_once()
            args = mock_send.call_args.args
            recipient = args[1]
            subject = args[2]
            body = args[3]

            self.assertEqual(recipient, "camila@wingedtycoons.com")
            self.assertIn("PO #PO-2026", subject)
            self.assertIn("SELECTED SUPPLIER DETAILS", body)
            self.assertIn("Selected Supplier: Aero Global Spares Inc", body)
            self.assertIn("sales@aeroglobalspares.com", body)
            self.assertIn("Supplier Unit Cost: $3,200.00 USD", body)
            self.assertIn("Condition: FN", body)
            self.assertIn("FAA 8130-3 Dual Release", body)
            self.assertIn("Lead Time: 1-2 Days", body)
            self.assertIn("Miami, FL", body)
            self.assertIn("Projected Margin", body)


if __name__ == "__main__":
    unittest.main()
