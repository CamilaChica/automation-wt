from __future__ import annotations

import io
import asyncio
import base64
import os
import unittest
import uuid
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
                "message_id": f"supplier-message-{uuid.uuid4().hex}",
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

    def test_inventory_worker_bounds_live_and_backfill_fetch_batches(self):
        requested_limits = []

        def fetch_messages(_mailbox, *, limit):
            requested_limits.append(limit)
            return []

        worker = InventoryIngestionWorker(fetch_messages=fetch_messages)

        worker.poll_once()
        worker.poll_once(limit=100)

        self.assertEqual(requested_limits, [5, 5])
        self.assertEqual(worker.backfill_page_size, 5)

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
        worker._enqueue_waiting_rfqs = lambda _part_number: None
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

    def test_postgres_inventory_resume_uses_scoped_async_repository_reads(self):
        events = []
        records = SimpleNamespace(
            list_by_payload_value=AsyncMock(side_effect=lambda domain, _field, value: {
                ("rfqs", "Supplier_Sourcing"): {
                    "RFQ-MATCH": {"id": "RFQ-MATCH", "status": "Supplier_Sourcing"},
                    "RFQ-NO-MATCH": {"id": "RFQ-NO-MATCH", "status": "Supplier_Sourcing"},
                },
                ("rfqs", "Sourcing_Failed"): {
                    "RFQ-FAILED": {"id": "RFQ-FAILED", "status": "Sourcing_Failed"},
                },
                ("rfqs", "Supplier_Confirmation_Requested"): {
                    "RFQ-STALE": {
                        "id": "RFQ-STALE",
                        "status": "Supplier_Confirmation_Requested",
                    },
                },
                ("rfq_items", "RFQ-MATCH"): {"ITEM-MATCH": {"resolved_part_number": "PN-1"}},
                ("rfq_items", "RFQ-FAILED"): {"ITEM-FAILED": {"resolved_part_number": "PN-1"}},
                ("rfq_items", "RFQ-STALE"): {"ITEM-STALE": {"resolved_part_number": "PN-1"}},
                ("rfq_items", "RFQ-NO-MATCH"): {"ITEM-OTHER": {"requested_part_number": "PN-2"}},
            }.get((domain, value), {})),
            has_domain=AsyncMock(return_value=True),
            record_automation_event=AsyncMock(side_effect=lambda **values: events.append(values) or "EVENT-1"),
        )
        rfq_repository = SimpleNamespace(list_by_status=AsyncMock(return_value=[]))
        repositories = SimpleNamespace(records=records, rfq=rfq_repository)

        class Engine:
            disposed = False

            async def dispose(self):
                self.disposed = True

        engine = Engine()

        @asynccontextmanager
        async def fake_session_scope(_engine):
            yield object()

        class StoreStub:
            storage_engine = "postgresql"

            @staticmethod
            def record_automation_event(**values):
                events.append(values)
                return "EVENT-1"

        worker = InventoryIngestionWorker(fetch_messages=lambda _mailbox, limit: [])
        with (
            patch("services.inventory_ingestion_worker.operations_store", StoreStub()),
            patch("services.inventory_ingestion_worker.create_engine_from_environment", return_value=engine),
            patch("services.inventory_ingestion_worker.session_scope", fake_session_scope),
            patch("repositories.runtime.create_operational_repositories", return_value=repositories),
        ):
            worker._enqueue_waiting_rfqs("pn-1")

        self.assertEqual(
            records.list_by_payload_value.await_args_list,
            [
                unittest.mock.call("rfqs", "status", "Supplier_Sourcing"),
                unittest.mock.call("rfqs", "status", "Sourcing_Failed"),
                unittest.mock.call("rfqs", "status", "No_Quote"),
                unittest.mock.call("rfqs", "status", "Supplier_Confirmation_Requested"),
                unittest.mock.call("rfq_items", "rfq_id", "RFQ-MATCH"),
                unittest.mock.call("rfq_items", "rfq_id", "RFQ-NO-MATCH"),
                unittest.mock.call("rfq_items", "rfq_id", "RFQ-FAILED"),
                unittest.mock.call("rfq_items", "rfq_id", "RFQ-STALE"),
            ],
        )
        rfq_repository.list_by_status.assert_not_awaited()
        records.has_domain.assert_not_awaited()
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0]["entity_id"], "RFQ-MATCH")
        self.assertEqual(events[0]["idempotency_key"], "rfq-resume:RFQ-MATCH:PN-1")
        self.assertEqual(events[1]["entity_id"], "RFQ-FAILED")
        self.assertEqual(events[1]["idempotency_key"], "rfq-resume:RFQ-FAILED:PN-1")
        self.assertEqual(events[2]["entity_id"], "RFQ-STALE")
        self.assertEqual(events[2]["idempotency_key"], "rfq-resume:RFQ-STALE:PN-1")
        self.assertTrue(engine.disposed)

        events.clear()
        engine.disposed = False
        async def relational_records(domain, _field, _value):
            if domain == "rfq_items":
                return {"ITEM-RELATIONAL": {"requested_part_number": "PN-1"}}
            return {}

        records.list_by_payload_value = AsyncMock(side_effect=relational_records)
        records.has_domain = AsyncMock(return_value=False)
        rfq_repository.list_by_status = AsyncMock(side_effect=[
            [SimpleNamespace(id="RFQ-RELATIONAL", status="Supplier_Sourcing")],
            [],
            [],
            [],
        ])
        with (
            patch("services.inventory_ingestion_worker.operations_store", StoreStub()),
            patch("services.inventory_ingestion_worker.create_engine_from_environment", return_value=engine),
            patch("services.inventory_ingestion_worker.session_scope", fake_session_scope),
            patch("repositories.runtime.create_operational_repositories", return_value=repositories),
        ):
            worker._enqueue_waiting_rfqs("PN-1")

        self.assertEqual(
            rfq_repository.list_by_status.await_args_list,
            [
                unittest.mock.call("Supplier_Sourcing"),
                unittest.mock.call("Sourcing_Failed"),
                unittest.mock.call("No_Quote"),
                unittest.mock.call("Supplier_Confirmation_Requested"),
            ],
        )
        records.has_domain.assert_awaited_once_with("rfqs")
        self.assertEqual(events[0]["entity_id"], "RFQ-RELATIONAL")
        self.assertTrue(engine.disposed)

        events.clear()
        engine.disposed = False
        records.list_by_payload_value = AsyncMock(return_value={})
        records.has_domain = AsyncMock(return_value=True)
        rfq_repository.list_by_status.reset_mock()
        with (
            patch("services.inventory_ingestion_worker.operations_store", StoreStub()),
            patch("services.inventory_ingestion_worker.create_engine_from_environment", return_value=engine),
            patch("services.inventory_ingestion_worker.session_scope", fake_session_scope),
            patch("repositories.runtime.create_operational_repositories", return_value=repositories),
        ):
            worker._enqueue_waiting_rfqs("PN-1")

        rfq_repository.list_by_status.assert_not_awaited()
        self.assertEqual(events, [])
        self.assertTrue(engine.disposed)

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
        self.assertIn("Does this quotation meet your needs?", followup["body"])
        self.assertIn("https://portal.wingedtycoons.com/customer-portal", followup["body"])
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

    def test_async_purchase_order_notification_queues_attachment_bytes(self):
        captured = {}

        class Records:
            async def enqueue_outbox_message(self, **values):
                captured.update(values)
                return {"id": "OUT-PO-ATTACHMENT", "status": "PENDING"}

        result = asyncio.run(CommunicationService().notify_purchase_order_async(
            SimpleNamespace(records=Records()),
            recipient="camila@wingedtycoons.com",
            po_number="PO-1002",
            customer_name="Global Airlines",
            customer_email="buyer@global.example",
            quote_id="QTE-1002",
            items=[],
            attachments=[{
                "filename": "purchase-order.pdf",
                "content_type": "application/pdf",
                "content": b"%PDF-test",
            }, {
                "filename": "export-certificate.pdf",
                "content_type": "application/pdf",
                "content": b"%PDF-export",
            }, {
                "filename": "kyc.docx",
                "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "content": b"PK-supporting-doc",
            }],
        ))

        queued_attachment = captured["attachments"][0]
        self.assertEqual(result["transmission_status"], "PENDING")
        self.assertEqual(queued_attachment["filename"], "purchase-order.pdf")
        self.assertEqual(
            base64.b64decode(queued_attachment["content_base64"]),
            b"%PDF-test",
        )
        self.assertEqual(len(captured["attachments"]), 3)
        self.assertEqual(base64.b64decode(captured["attachments"][1]["content_base64"]), b"%PDF-export")
        self.assertEqual(base64.b64decode(captured["attachments"][2]["content_base64"]), b"PK-supporting-doc")

    def test_inventory_table_does_not_bypass_certificate_review(self):
        from tests.test_document_parser import certificate_pdf

        records = SimpleNamespace(
            claim_inbound_message=AsyncMock(return_value=True),
            archive_raw_email=AsyncMock(),
            mark_inbound_message_processed=AsyncMock(),
            set_raw_email_processing_status=AsyncMock(),
        )
        repositories = SimpleNamespace(records=records)

        @asynccontextmanager
        async def fake_session_scope(_engine):
            yield object()

        worker = InventoryIngestionWorker(fetch_messages=lambda _mailbox, limit: [])
        with (
            patch("services.inventory_ingestion_worker.session_scope", fake_session_scope),
            patch("repositories.runtime.create_operational_repositories", return_value=repositories),
            patch.object(worker.loader.ingestion_service, "ingest_email_async", new_callable=AsyncMock) as ingest,
            patch("services.inventory_ingestion_worker.import_inventory_attachments_async", new_callable=AsyncMock) as import_table,
        ):
            ingest.return_value = {"success": False, "status": "Pending_Human_Review"}
            result = asyncio.run(worker._process_inventory_table_message_async({
                "message_id": "inventory-doc-review",
                "body": "Inventory attached",
                "attachments": [
                    {"filename": "inventory.csv", "content": b"PN,Quantity\nPN-123,1"},
                    {"filename": "cert-a.pdf", "content": certificate_pdf(serial_number="SN-1")},
                    {"filename": "cert-b.pdf", "content": certificate_pdf(serial_number="SN-2")},
                ],
            }, engine=object()))
        self.assertFalse(result["success"])
        import_table.assert_not_awaited()
        ingest.assert_awaited_once()
        records.set_raw_email_processing_status.assert_awaited_once_with(
            "purchasing", "inventory-doc-review", "pending_human_review",
        )


if __name__ == "__main__":
    unittest.main()
