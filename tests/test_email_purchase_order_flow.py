import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services.operations_store import OperationsStore
from worker import _ingest_sales_message


class TestEmailPurchaseOrderFlow(unittest.TestCase):
    def test_email_po_creates_relational_record_and_alert(self):
        rfq = SimpleNamespace(
            id="RFQ-PO-1", customer_email="buyer@example.com", customer_name="Buyer", status="Quote_Sent",
            thread_id="original-message",
        )
        quote = SimpleNamespace(id="QTE-PO-1", rfq_id=rfq.id, total_amount=250.0)
        quote_item = SimpleNamespace(part_number="060-1234-00", quantity=2, unit_price=125.0, unit_cost=100.0)
        message = {
            "message_id": "graph-message-po-1",
            "internet_message_id": "<po-1@example.com>",
            "from": "buyer@example.com",
            "subject": "Purchase Order Number: WT-PO-555",
            "body": "Please find our purchase order attached.",
            "attachments": [{"filename": "WT-PO-555.pdf", "content_type": "application/pdf", "content": b"pdf"}],
        }
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "ENVIRONMENT": "local", "WT_ENV": "local", "WT_AUTH_ENV": "local", "RENDER": "false",
            "CAMILA_NOTIFICATION_EMAIL": "camila@wingedtycoons.com",
            "EMAIL_SEND_ENABLED": "false",
        }, clear=False):
            store = OperationsStore(os.path.join(directory, "po-flow.db"))
            connection = store._connect()
            try:
                connection.execute(
                    "INSERT INTO rfqs (id, quantity, status, created_at, updated_at) VALUES (?, 2, 'Quote_Sent', '2026-09-27', '2026-09-27')",
                    (rfq.id,),
                )
                connection.execute(
                    "INSERT INTO customer_quotes (id, rfq_id, quote_number, unit_price, quantity, total_price, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, 125, 2, 250, 'Sent', '2026-09-27', '2026-09-27')",
                    (quote.id, rfq.id, quote.id),
                )
                connection.commit()
            finally:
                connection.close()

            with (
                patch("worker.operations_store", store),
                patch("worker.db_service.list_rfqs", return_value=[rfq]),
                patch("worker.db_service.get_quote_by_rfq", return_value=quote),
                patch("worker.db_service.get_quote_items", return_value=[quote_item]),
                patch("worker.supplier_db.find_supplier_offers", return_value=[]),
                patch("worker.communication_service.cancel_customer_followups"),
                patch("worker.communication_service.send_customer_receipt", return_value={"transmission_status": "DRY_RUN"}),
                patch("worker.communication_service.notify_purchase_order", return_value={"transmission_status": "PENDING"}) as notify,
                patch("worker.orchestration_service.mark_purchase_order_received") as mark_received,
            ):
                self.assertTrue(asyncio.run(_ingest_sales_message(message)))

            connection = store._connect()
            try:
                po = connection.execute(
                    "SELECT po_number, customer_email, quote_id, rfq_id, status, received_message_id "
                    "FROM purchase_orders WHERE po_number = ?", ("WT-PO-555",),
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(tuple(po), (
            "WT-PO-555", "buyer@example.com", "QTE-PO-1", "RFQ-PO-1", "Pending_PO_Review", "<po-1@example.com>",
        ))
        notify.assert_called_once()
        self.assertIn("camila@", notify.call_args.kwargs["recipient"])
        self.assertEqual(
            notify.call_args.kwargs["attachments"],
            [{
                "filename": "WT-PO-555.pdf",
                "content_type": "application/pdf",
                "content": b"pdf",
            }],
        )
        mark_received.assert_called_once_with("RFQ-PO-1", "WT-PO-555", ["WT-PO-555.pdf"])


if __name__ == "__main__":
    unittest.main()