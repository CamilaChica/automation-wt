from __future__ import annotations

import io
import os
import unittest
from unittest.mock import patch

from services.communication_service import CommunicationService
from services.db_service import db_service
from services.inventory_ingestion_worker import InventoryIngestionWorker
from services.supplier_email_loader import SupplierEmailLoader
from services.supplier_database import supplier_db


class CapturingLoader:
    def __init__(self):
        self.email_text = ""

    def load_raw_email_text(self, email_text, **kwargs):
        self.email_text = email_text
        return {
            "success": True,
            "supplier_name": "Aero Supplier",
            "supplier_email": "quotes@aero.example",
            "part_number": "060-1234-00",
            "quantity_available": 12,
            "unit_cost": 1100.0,
            "certificate_type": "FAA 8130-3",
            "lead_time_days": 3,
            "source_email_id": kwargs.get("message_id") or "EMAIL-TEST",
            "trace_documents": ["FAA 8130-3"],
        }


class TestFullSalesAndIngestionPipeline(unittest.TestCase):
    def setUp(self):
        db_service.rfqs.clear()
        db_service.rfq_items.clear()
        db_service.quotes.clear()
        db_service.quote_items.clear()
        db_service.audit_logs.clear()

    def test_inventory_worker_ingests_subject_and_attachment_context(self):
        loader = CapturingLoader()
        worker = InventoryIngestionWorker(
            fetch_messages=lambda mailbox, limit: [{
                "message_id": "supplier-message-1",
                "from": "quotes@aero.example",
                "subject": "Quote 060-1234-00 - FAA 8130-3",
                "body": "Quantity available: 12\nUnit price: $1,100.00\nLead time: 3 days",
                "attachments": [{
                    "filename": "inventory.csv",
                    "content_type": "text/csv",
                    "content": b"Part Number,Quantity,Condition\n060-1234-00,12,NE",
                }],
            }],
            loader=loader,
        )
        results = worker.poll_once(limit=1)

        self.assertTrue(results[0]["success"])
        self.assertIn("Subject: Quote 060-1234-00", loader.email_text)
        self.assertIn("Attachment inventory.csv:", loader.email_text)
        self.assertIn("060-1234-00,12,NE", loader.email_text)

    def test_real_supplier_loader_parses_subject_part_number(self):
        loader = SupplierEmailLoader()
        result = loader.load_raw_email_text(
            "From: quotes@aero.example\n"
            "Subject: Quote for P/N 060-1234-00 - FAA 8130-3\n\n"
            "Quantity available: 4\nUnit price: $1,100.00\nLead time: 3 days\n"
            "Condition: NE\nFAA 8130-3 attached.",
            mailbox="purchasing",
            message_id="subject-part-test",
        )

        self.assertTrue(result["success"], result)
        self.assertEqual(result["part_number"], "060-1234-00")
        self.assertEqual(result["quantity_available"], 4)
        self.assertEqual(result["certificate_type"], "FAA 8130-3")

    def test_customer_followup_and_supplier_discount_are_scheduled(self):
        service = CommunicationService()
        followup = service.schedule_customer_followup(
            recipient="buyer@example.com",
            customer_name="Buyer",
            quote_id="QTE-123456",
            customer_timezone="UTC",
        )
        discount = service.schedule_supplier_discount_request(
            recipient="quotes@supplier.example",
            supplier_name="Supplier",
            part_number="060-1234-00",
            unit_cost=1100.0,
            source_email_id="EMAIL-123",
            quantity=25,
        )

        self.assertEqual(followup["task_key"], "customer-followup:QTE-123456")
        self.assertEqual(discount["task_key"], "supplier-discount:EMAIL-123:1")
        tasks = supplier_db.list_due_communication_tasks("9999-12-31T00:00:00+00:00")
        task_types = {task["task_type"] for task in tasks}
        self.assertIn("customer_followup", task_types)
        self.assertIn("supplier_discount_request", task_types)

    @patch.object(CommunicationService, "_send")
    def test_purchase_order_notification_targets_configured_camila_address(self, mock_send):
        mock_send.return_value = {"transmission_status": "DRY_RUN", "communication_id": "COM-PO-1"}
        with patch.dict(os.environ, {"PURCHASE_ORDER_NOTIFICATION_EMAIL": "camila@wingedtycoons.com"}, clear=False):
            result = CommunicationService().notify_purchase_order(
                recipient="camila@wingedtycoons.com",
                po_number="PO-1001",
                customer_name="Global Airlines",
                customer_email="buyer@global.example",
                quote_id="QTE-1001",
                items=[{
                    "part_number": "060-1234-00",
                    "quantity": 1,
                    "unit_price": 12500.0,
                    "supplier_name": "Aero Supplier",
                    "supplier_unit_cost": 10000.0,
                }],
            )

        self.assertEqual(result["transmission_status"], "DRY_RUN")
        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args.args[1], "camila@wingedtycoons.com")
        self.assertIn("PO-1001", mock_send.call_args.args[3])
        self.assertIn("Global Airlines", mock_send.call_args.args[3])


if __name__ == "__main__":
    unittest.main()
