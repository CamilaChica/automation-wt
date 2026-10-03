import asyncio
import unittest
from unittest.mock import patch

from services.db_service import db_service
from services.email_intelligence import CommunicationSentiment
from worker import _ingest_sales_message


class TestCustomerReplyPipeline(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
