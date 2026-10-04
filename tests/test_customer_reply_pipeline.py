import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from services.db_service import db_service
from services.email_intelligence import CommunicationSentiment
from worker import _ingest_existing_sales_message_async, _ingest_sales_message, _automated_sender


class TestCustomerReplyPipeline(unittest.TestCase):
    def test_automated_mail_does_not_generate_customer_replies(self):
        self.assertTrue(_automated_sender({"from": "mailer-daemon@example.com"}))
        self.assertTrue(_automated_sender({
            "from": "buyer@example.com", "headers": [{"name": "Auto-Submitted", "value": "auto-replied"}],
        }))
        self.assertFalse(_automated_sender({"from": "buyer@example.com"}))

    def test_unmatched_customer_message_is_acknowledged_and_reviewed(self):
        message = {"from": "new@example.invalid", "message_id": "NEW-1",
                   "subject": "Hello", "body": "Thank you", "attachments": []}
        with (
            patch("worker.communication_service.send_customer_receipt") as receipt,
            patch("worker._review_inbound_customer_message") as review,
        ):
            self.assertTrue(asyncio.run(_ingest_sales_message(message)))
        receipt.assert_called_once()
        self.assertEqual(receipt.call_args.kwargs["reply_to"], "NEW-1")
        review.assert_called_once()

    def test_confirmed_pn_closes_only_after_response_accepted(self):
        self.rfq.status = "Supplier_Sourcing"
        db_service.quotes.clear()
        item = db_service.get_rfq_items(self.rfq.id)[0]
        item.resolved_part_number = item.requested_part_number
        message = {"from": self.rfq.customer_email, "message_id": "CONFIRM-1",
                   "subject": f"Re: Request {self.rfq.id}",
                   "body": "I confirm 060-1234-00 is correct.", "attachments": []}
        with (
            patch("worker.orchestration_service._load_pipeline_state",
                  return_value={"pn_confirmation_required": ["060-1234-00"]}),
            patch("worker.orchestration_service._save_pipeline_state") as save,
            patch("worker.db_service.get_supplier_offers_for_part", return_value=[]),
            patch("worker.db_service.inventory", {}),
            patch("worker.communication_service.send_rfq_update_reply",
                  side_effect=TimeoutError("mail queue unavailable")),
        ):
            with self.assertRaises(TimeoutError):
                asyncio.run(_ingest_sales_message(message))
        save.assert_not_called()
        self.assertEqual(self.rfq.status, "Supplier_Sourcing")
        with (
            patch("worker.orchestration_service._load_pipeline_state",
                  return_value={"pn_confirmation_required": ["060-1234-00"]}),
            patch("worker.orchestration_service._save_pipeline_state"),
            patch("worker.db_service.get_supplier_offers_for_part", return_value=[]),
            patch("worker.db_service.inventory", {}),
            patch("worker.communication_service.send_rfq_update_reply") as reply,
        ):
            asyncio.run(_ingest_sales_message(message))
        self.assertIn("No Quote", reply.call_args.kwargs["quote_answer"])
        self.assertEqual(db_service.get_rfq(self.rfq.id).status, "No_Quote")

    def test_async_confirmation_is_durable_and_keeps_other_lines_open(self):
        rfq = SimpleNamespace(id="RFQ-MIX", customer_name="Buyer", customer_email="buyer@example.invalid",
                              status="Supplier_Sourcing", automation_paused=False, thread_id="THREAD",
                              created_at=datetime.now(timezone.utc))
        repositories = SimpleNamespace(
            rfq=SimpleNamespace(
                get_operational_record=AsyncMock(return_value={"pn_confirmation_required": ["ABC123"]}),
                list_operational_records=AsyncMock(side_effect=[{}, {
                    "ONE": {"rfq_id": rfq.id, "requested_part_number": "ABC123"},
                    "TWO": {"rfq_id": rfq.id, "requested_part_number": "XYZ9"},
                }]),
                record_pn_confirmation=AsyncMock(),
            ),
            supplier=SimpleNamespace(offers_for_part=AsyncMock(return_value=[])),
            quote=SimpleNamespace(list_operational_records=AsyncMock(return_value={})),
            records=SimpleNamespace(enqueue_operator_review=AsyncMock()),
        )
        message = {"from": rfq.customer_email, "message_id": "CONFIRM-2",
                   "subject": f"Re: Request {rfq.id}", "body": "I confirm ABC123 is correct."}
        with (
            patch("worker.db_service.list_rfqs_async", new=AsyncMock(return_value=[rfq])),
            patch("worker.communication_service.send_rfq_update_reply_async", new_callable=AsyncMock) as reply,
        ):
            asyncio.run(_ingest_existing_sales_message_async(message, repositories))
        repositories.rfq.record_pn_confirmation.assert_awaited_once_with(rfq.id, ["ABC123"], False)
        repositories.records.enqueue_operator_review.assert_awaited_once()
        self.assertIn("other lines", reply.call_args.kwargs["quote_answer"])

    def setUp(self):
        db_service.rfqs.clear()
        db_service.rfq_items.clear()
        db_service.quotes.clear()
        db_service.quote_items.clear()
        db_service.audit_logs.clear()
        rfq = db_service.create_rfq("Global Airlines", "buyer@global.example", "P/N 060-1234-00 qty 1")
        item = db_service.add_rfq_item(rfq.id, "060-1234-00", 1, condition="NE")
        quote = db_service.create_quote(rfq.id, 1200.0, 0.0, 1200.0, lead_time_days=3)
        db_service.add_quote_item(
            quote.id, item.id, "060-1234-00", 1, "Inventory", 900.0, 1200.0, 25.0,
            "FAA 8130-3", "Pass", condition="NE", lead_time_days=3,
        )
        rfq.status = "Quote_Sent"
        db_service._persist_state()
        self.rfq = rfq
        self.quote = quote

    def test_detail_request_replies_in_existing_thread(self):
        sentiment_result = CommunicationSentiment(
            label="negative",
            confidence=88,
            evidence=["Please send the certificate today."],
        )
        sentiment = sentiment_result.model_dump()
        with (
            patch("worker.communication_service.send_customer_information_response") as send_response,
            patch(
                "worker.analyze_communication_sentiment",
                return_value=sentiment_result,
            ),
            patch("worker.operations_store.record_automation_event") as record_sentiment,
        ):
            send_response.return_value = {"communication_id": "COM-DETAIL-1", "transmission_status": "DRY_RUN"}
            asyncio.run(_ingest_sales_message({
                "message_id": "customer-reply-1",
                "from": "buyer@global.example",
                "subject": f"Re: Quotation {self.quote.id} - need certificate",
                "body": "Please send the FAA 8130-3 certificate and shipping dimensions.",
                "attachments": [],
            }))

        send_response.assert_called_once()
        self.assertEqual(send_response.call_args.kwargs["quote_id"], self.quote.id)
        self.assertEqual(send_response.call_args.kwargs["reply_to"], "customer-reply-1")
        self.assertEqual(send_response.call_args.kwargs["communication_sentiment"], sentiment)
        record_sentiment.assert_called_once()
        self.assertTrue(any(log.action_type == "customer_detail_response" for log in db_service.get_audit_logs(self.rfq.id)))

    def test_unknown_catalog_part_is_resolved_to_requested_number_for_sourcing(self):
        item = db_service.get_rfq_items(self.rfq.id)[0]

        resolved = db_service.resolve_rfq_item(item.id, item.requested_part_number)

        self.assertEqual(resolved.resolved_part_number, item.requested_part_number)
        self.assertEqual(
            db_service.get_rfq_items(self.rfq.id)[0].resolved_part_number,
            item.requested_part_number,
        )


if __name__ == "__main__":
    unittest.main()
