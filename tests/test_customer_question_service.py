import asyncio
import base64
import unittest
from email.message import EmailMessage
from unittest.mock import AsyncMock, Mock, patch

from services.communication_service import (
    _source_documents_for_customer_request,
    communication_service,
)
from services.customer_question_service import CustomerQuestionService
from tests.test_document_parser import certificate_pdf


class CustomerQuestionServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = CustomerQuestionService()

    def test_answers_warranty_and_lead_time_from_async_record_dicts(self):
        answer = self.service.answer_from_quote(
            "What is the warranty and lead time?",
            {"lead_time_days": 4},
            [{
                "part_number": "PN-123",
                "lead_time_days": 3,
                "warranty_terms": "Six months from delivery",
            }],
        )

        self.assertIn("PN-123: Six months from delivery", answer)
        self.assertIn("PN-123: 3 days", answer)

    def test_finds_requested_trace_document_from_async_record_dict(self):
        message = EmailMessage()
        message.set_content("Supplier quote")
        message.add_attachment(
            certificate_pdf(),
            maintype="application",
            subtype="pdf",
            filename="FAA_8130_certificate.pdf",
        )
        with patch(
            "services.communication_service.operations_store.get_raw_email_mime",
            return_value=message.as_bytes(),
        ):
            attachments = _source_documents_for_customer_request(
                "Please send the certificate for this part.",
                [{
                    "part_number": "PN-123",
                    "source_email_id": "supplier-message-1",
                    "trace_documents": '["FAA_8130_certificate.pdf"]',
                }],
            )

        self.assertEqual(attachments[0]["filename"], "FAA_8130_certificate.pdf")
        self.assertEqual(attachments[0]["content"], certificate_pdf())

    def test_async_customer_document_reply_queues_attachment_bytes(self):
        message = EmailMessage()
        message.set_content("Supplier quote")
        message.add_attachment(
            certificate_pdf(),
            maintype="application",
            subtype="pdf",
            filename="FAA_8130_certificate.pdf",
        )
        repositories = Mock()
        repositories.records = Mock()
        repositories.records.enqueue_outbox_message = AsyncMock(
            return_value={"id": "OUT-1", "status": "QUEUED"}
        )
        with patch(
            "services.communication_service.operations_store.get_raw_email_mime",
            return_value=message.as_bytes(),
        ):
            asyncio.run(communication_service.send_customer_information_response_async(
                repositories,
                recipient="buyer@example.com",
                customer_name="Buyer",
                quote_id="QTE-1234",
                request_text="Please send the certificate.",
                quote={"lead_time_days": 3, "valid_until": "2026-12-31"},
                items=[{
                    "part_number": "PN-123",
                    "quantity": 1,
                    "unit_price": 1200,
                    "certificate_type": "FAA 8130-3",
                    "source_email_id": "supplier-message-1",
                    "trace_documents": ["FAA_8130_certificate.pdf"],
                }],
            ))

        queued_payload = repositories.records.enqueue_outbox_message.call_args.kwargs
        self.assertIsNotNone(queued_payload["html_body"])
        self.assertEqual(
            queued_payload["attachments"][0]["content_base64"],
            base64.b64encode(certificate_pdf()).decode("ascii"),
        )

    def test_other_parts_and_supplier_prices_are_not_attached(self):
        message = EmailMessage()
        message.set_content("Supplier quote")
        for name, content in [
            ("cert-right.pdf", certificate_pdf()),
            ("cert-other.pdf", certificate_pdf(part_number="PN-999")),
            ("cert-priced.pdf", certificate_pdf(extra="Unit Price: USD 1000")),
        ]:
            message.add_attachment(content, maintype="application", subtype="pdf", filename=name)
        with patch("services.communication_service.operations_store.get_raw_email_mime", return_value=message.as_bytes()):
            attachments = _source_documents_for_customer_request(
                "Please send the certificate for PN-123.",
                [{"part_number": "PN-123", "source_email_id": "supplier-message-1"}],
            )
        self.assertEqual([attachment["filename"] for attachment in attachments], ["cert-right.pdf"])

    def test_unreadable_supplier_certificate_is_not_released(self):
        message = EmailMessage()
        message.set_content("Supplier quote")
        message.add_attachment(b"invalid", maintype="application", subtype="pdf", filename="cert.pdf")
        with patch("services.communication_service.operations_store.get_raw_email_mime", return_value=message.as_bytes()):
            with self.assertRaisesRegex(ValueError, "requested_document_unavailable"):
                _source_documents_for_customer_request(
                    "Please send the certificate.",
                    [{"part_number": "PN-123", "source_email_id": "supplier-message-1"}],
                )

    def test_async_purchase_order_notification_queues_real_file(self):
        repositories = Mock()
        repositories.records = Mock()
        repositories.records.enqueue_outbox_message = AsyncMock(
            return_value={"id": "OUT-PO-1", "status": "QUEUED"}
        )

        asyncio.run(communication_service.notify_purchase_order_async(
            repositories,
            recipient="camila@wingedtycoons.com",
            po_number="PO-1234",
            customer_name="Buyer",
            customer_email="buyer@example.com",
            quote_id="QTE-1234",
            items=[{
                "part_number": "PN-123",
                "quantity": 1,
                "unit_price": 1200,
                "supplier_unit_cost": 900,
            }],
            attachments=[{
                "filename": "PO-1234.pdf",
                "content_type": "application/pdf",
                "content": b"purchase-order",
            }],
        ))

        queued_payload = repositories.records.enqueue_outbox_message.call_args.kwargs
        self.assertEqual(
            queued_payload["attachments"][0]["content_base64"],
            base64.b64encode(b"purchase-order").decode("ascii"),
        )

    def test_answers_worldwide_shipping_inquiry(self):
        answer = self.service.answer_from_quote(
            "Do you offer worldwide shipping or international delivery?",
            {"valid_until": "2026-12-31"},
            [{"part_number": "PN-123", "quantity": 1}],
        )
        self.assertIsNotNone(answer)
        self.assertIn("worldwide delivery", answer.lower())

    def test_answers_exchange_policy_inquiry(self):
        answer = self.service.answer_from_quote(
            "Can we do a core exchange on this part?",
            {"valid_until": "2026-12-31"},
            [{"part_number": "PN-123", "quantity": 1}],
        )
        self.assertIsNotNone(answer)
        self.assertIn("outright purchase only", answer.lower())

    def test_answers_unit_location_inquiry(self):
        answer = self.service.answer_from_quote(
            "Where is the unit located?",
            {"valid_until": "2026-12-31"},
            [{"part_number": "PN-123", "quantity": 1, "availability_location": "Miami, FL"}],
        )
        self.assertIsNotNone(answer)
        self.assertIn("Miami, FL", answer)


if __name__ == "__main__":
    unittest.main()
