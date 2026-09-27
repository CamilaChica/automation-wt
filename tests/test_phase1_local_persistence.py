import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from services.operations_store import OperationsStore
from services import supplier_inventory_importer


class TestPhaseOneLocalPersistence(unittest.TestCase):
    def test_inventory_attachment_import_upserts_and_audits_every_row(self):
        csv_content = (
            "Part Number,Description,Quantity,Condition,Unit Price,Currency,Lead Time,Certificate\n"
            "060-1234-00,Actuator,5,OH,125.50,USD,4 days,FAA 8130-3\n"
            ",Missing part,2,NE,10,USD,,\n"
        ).encode()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "ENVIRONMENT": "local", "WT_ENV": "local", "WT_AUTH_ENV": "local", "RENDER": "false",
        }, clear=False):
            store = OperationsStore(os.path.join(directory, "imports.db"))
            with patch.object(supplier_inventory_importer, "operations_store", store), patch.object(
                supplier_inventory_importer, "_save_offer", return_value={"id": "offer-1"},
            ) as save_offer:
                result = supplier_inventory_importer.import_inventory_attachments({
                    "message_id": "graph-message-1",
                    "internet_message_id": "<supplier-stock@example.com>",
                    "from": "Stock Supplier <inventory@supplier.example>",
                    "attachments": [{
                        "filename": "stock.csv", "content_type": "text/csv", "content": csv_content,
                    }],
                }, "purchasing")

            self.assertTrue(result["success"])
            self.assertEqual(result["imports"][0]["rows_imported"], 1)
            self.assertEqual(result["imports"][0]["rows_rejected"], 1)
            self.assertEqual(save_offer.call_count, 1)
            connection = store._connect()
            try:
                rows = connection.execute(
                    "SELECT part_number, status FROM supplier_inventory_rows ORDER BY row_number"
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual([tuple(row) for row in rows], [("060-1234-00", "imported"), (None, "rejected")])

    def test_incomplete_supplier_offer_is_held_and_requests_missing_fields(self):
        csv_content = (
            "Part Number,Description,Quantity,Condition\n"
            "060-1234-00,Actuator,5,OH\n"
        ).encode()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "ENVIRONMENT": "local", "WT_ENV": "local", "WT_AUTH_ENV": "local", "RENDER": "false",
        }, clear=False):
            store = OperationsStore(os.path.join(directory, "followup.db"))
            with patch.object(supplier_inventory_importer, "operations_store", store), patch.object(
                supplier_inventory_importer, "_save_offer",
            ) as save_offer, patch.object(
                supplier_inventory_importer.communication_service,
                "request_missing_supplier_fields",
                return_value={"transmission_status": "PENDING", "outbox_id": "OUT-1"},
            ) as request_followup:
                result = supplier_inventory_importer.import_inventory_attachments({
                    "message_id": "graph-stock-2",
                    "internet_message_id": "<stock-2@supplier.example>",
                    "from": "Stock Supplier <inventory@supplier.example>",
                    "attachments": [{"filename": "incomplete.csv", "content_type": "text/csv", "content": csv_content}],
                }, "purchasing")

            self.assertEqual(result["status"], "Inventory_Followup_Requested")
            self.assertEqual(result["imports"][0]["status"], "awaiting_supplier_data")
            self.assertEqual(result["imports"][0]["rows_imported"], 0)
            self.assertEqual(result["imports"][0]["rows_rejected"], 1)
            self.assertEqual(result["imports"][0]["supplier_followups"][0]["part_number"], "060-1234-00")
            save_offer.assert_not_called()
            request_followup.assert_called_once()
            self.assertIn("unit price and currency", request_followup.call_args.kwargs["missing_fields"])
            self.assertIn("lead time", request_followup.call_args.kwargs["missing_fields"])
            self.assertEqual(request_followup.call_args.kwargs["reply_to"], "graph-stock-2")

    def test_automation_events_are_claimed_once_for_background_work(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "ENVIRONMENT": "local", "WT_ENV": "local", "WT_AUTH_ENV": "local", "RENDER": "false",
        }, clear=False):
            store = OperationsStore(os.path.join(directory, "queue.db"))
            event_id = store.record_automation_event(
                event_type="resume_waiting_rfq", entity_type="rfq", entity_id="RFQ-1", status="QUEUED",
                result='{"part_number":"060-1234-00"}', idempotency_key="resume:RFQ-1:060-1234-00",
            )

            claimed = store.claim_automation_events(event_type="resume_waiting_rfq", limit=1)

            self.assertEqual([event["id"] for event in claimed], [event_id])
            self.assertEqual(claimed[0]["attempts"], 1)
            self.assertEqual(store.claim_automation_events(event_type="resume_waiting_rfq", limit=1), [])

    def test_stable_dedupe_archive_audit_and_inventory_rows_use_local_sqlite(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "ENVIRONMENT": "local",
            "WT_ENV": "local",
            "WT_AUTH_ENV": "local",
            "RENDER": "false",
        }, clear=False):
            store = OperationsStore(os.path.join(directory, "phase1.db"))

            self.assertTrue(store.claim_inbound_message("graph-id-1", "sales", "<CaseSensitive@Example.com>"))
            self.assertFalse(store.claim_inbound_message("graph-id-moved", "sales", "<casesensitive@example.com>"))
            store.save_raw_email(
                mailbox="sales", provider_message_id="graph-id-1", internet_message_id="<CaseSensitive@Example.com>",
                sender="buyer@example.com", subject="RFQ", body="Part Number 060-1234-00",
                raw_mime=b"From: buyer@example.com\r\n\r\nRFQ", headers=[{"name": "Message-ID", "value": "<CaseSensitive@Example.com>"}],
                attachments=[{"filename": "stock.csv", "content_type": "text/csv", "size": 40}],
            )
            audit = store.insert_audit_log(
                rfq_id="RFQ-1", agent_name="RFQIntakeAgent", action_type="parse", message="Parsed locally",
                status="SUCCESS", payload_json=None, timestamp=datetime.now(timezone.utc),
            )
            self.assertEqual(store.list_audit_logs("RFQ-1")[0]["id"], audit["id"])

            import_id = store.record_inventory_import(
                mailbox="purchasing", source_message_id="internet-id-1", sender="supplier@example.com",
                filename="stock.csv", content_sha256="a" * 64, parser="csv", sheet_name=None,
                header_map={"part_number": "PN"}, rows_total=1, rows_imported=1, rows_rejected=0,
                rejected_rows=[], status="imported",
            )
            store.record_inventory_rows(import_id, [{
                "id": "SIR-1", "row_number": 1, "part_number": "060-1234-00", "quantity_available": 3,
                "raw_values": {"PN": "060-1234-00"}, "status": "imported",
            }])
            connection = store._connect()
            try:
                connection.execute(
                    "INSERT INTO rfqs (id, quantity, status, created_at, updated_at) VALUES ('RFQ-1', 1, 'Quote_Sent', '2026-09-27', '2026-09-27')"
                )
                connection.execute(
                    "INSERT INTO customer_quotes (id, rfq_id, quote_number, unit_price, quantity, total_price, status, created_at, updated_at) "
                    "VALUES ('QTE-1', 'RFQ-1', 'QTE-1', 125, 1, 125, 'Sent', '2026-09-27', '2026-09-27')"
                )
                connection.commit()
                archived = connection.execute("SELECT raw_mime FROM raw_emails WHERE provider_message_id = ?", ("graph-id-1",)).fetchone()
                imported = connection.execute("SELECT part_number, status FROM supplier_inventory_rows WHERE id = ?", ("SIR-1",)).fetchone()
            finally:
                connection.close()

            purchase_order = store.record_purchase_order(
                po_id="PO-1", po_number="WT-PO-1", customer_email="buyer@example.com", total_amount=125,
                status="Pending_PO_Review", quote_id="QTE-1", rfq_id="RFQ-1", received_message_id="imid-1",
                attachment_metadata=[{"filename": "po.pdf"}],
            )
            duplicate_po = store.record_purchase_order(
                po_id="PO-2", po_number="WT-PO-1", customer_email="buyer@example.com", total_amount=125,
                status="Pending_PO_Review", quote_id="QTE-1", rfq_id="RFQ-1", received_message_id="imid-2",
                attachment_metadata=[],
            )

            self.assertEqual(archived["raw_mime"], b"From: buyer@example.com\r\n\r\nRFQ")
            self.assertEqual(tuple(imported), ("060-1234-00", "imported"))
            self.assertEqual(purchase_order["id"], duplicate_po["id"])


if __name__ == "__main__":
    unittest.main()