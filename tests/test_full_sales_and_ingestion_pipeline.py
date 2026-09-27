from __future__ import annotations

import io
import os
import unittest
from contextlib import contextmanager
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
                    "content": b"Part Number,Quantity,Condition,Unit Price,Lead Time,Certificate\n060-1234-00,12,NE,1100,3 days,FAA 8130-3",
                }],
            }],
            loader=loader,
        )
        results = worker.poll_once(limit=1)

        self.assertTrue(results[0]["success"])
        self.assertEqual(results[0]["result"]["status"], "Inventory_Table_Imported")
        self.assertEqual(results[0]["result"]["imports"][0]["rows_imported"], 1)
        self.assertEqual(loader.email_text, "")

    def test_inventory_worker_claim_and_business_processing_share_transaction(self):
        events = []

        class SharedStoreStub:
            storage_engine = "postgresql"

            @contextmanager
            def transaction(self):
                events.append("begin")
                try:
                    yield
                finally:
                    events.append("commit")

            def claim_inbound_message(self, message_id, mailbox, internet_message_id=None):
                events.append(("claim", message_id, mailbox))
                return True

            def mark_inbound_message_processed(self, message_id, internet_message_id=None):
                events.append(("processed", message_id))

            def release_inbound_message(self, message_id, internet_message_id=None):
                events.append(("released", message_id))

        class RecordingLoader(CapturingLoader):
            def load_raw_email_text(self, email_text, **kwargs):
                events.append(("ingest", kwargs["message_id"]))
                return super().load_raw_email_text(email_text, **kwargs)

        worker = InventoryIngestionWorker(
            fetch_messages=lambda mailbox, limit: [],
            loader=RecordingLoader(),
        )
        worker.postgres_enabled = False
        worker._resume_waiting_rfqs = lambda _part_number: None
        message = {
            "message_id": "supplier-shared-1",
            "from": "quotes@aero.example",
            "subject": "Quote for 060-1234-00",
            "body": "Quantity 12, unit price $1100, FAA 8130-3, lead time 3 days",
        }
        with (
            patch("services.inventory_ingestion_worker.operations_store", SharedStoreStub()),
            patch("services.inventory_ingestion_worker.supplier_db.is_email_processed", return_value=False),
            patch("services.inventory_ingestion_worker.communication_service.schedule_supplier_discount_request"),
            patch.object(worker.negotiation_service, "record_supplier_quote", return_value={"status": "BELOW_THRESHOLD"}),
        ):
            result = worker.process_message(message)

        self.assertTrue(result["success"])
        self.assertLess(events.index("begin"), events.index(("claim", "supplier-shared-1", "purchasing")))
        self.assertLess(events.index(("claim", "supplier-shared-1", "purchasing")), events.index(("ingest", "supplier-shared-1")))
        self.assertLess(events.index(("ingest", "supplier-shared-1")), events.index(("processed", "supplier-shared-1")))
        self.assertLess(events.index(("processed", "supplier-shared-1")), events.index("commit"))

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
