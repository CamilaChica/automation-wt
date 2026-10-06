"""Unit tests for Client Quote History Gathering & Querying."""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from services.client_history_service import ClientHistoryService
from services.customer_question_service import CustomerQuestionService
from services.operations_store import OperationsStore


class TestClientQuoteHistory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_client_history.db")
        self.service = ClientHistoryService(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_record_and_get_client_quote_history(self):
        # Record 2 quotes for part A and 1 quote for part B for client delta@example.com
        self.service.record_client_quote(
            client_email="delta@example.com",
            client_name="Delta Tech",
            company_name="Delta Airlines",
            quote_number="QTE-DELTA-001",
            rfq_id="RFQ-D1",
            part_number="060-1234-00",
            description="Altitude Transceiver Unit",
            quantity=2,
            unit_price=1250.0,
            total_price=2500.0,
            condition="NE",
            certification="FAA 8130-3 Dual Release",
            lead_time="Stock",
            valid_until="2026-11-15",
            status="Sent",
            sent_at="2026-10-01T10:00:00Z",
            email_subject="Quotation QTE-DELTA-001 - Part Number 060-1234-00",
            email_body="Dear Delta Tech,\nWe offer 060-1234-00 at $1,250.00 each.\nLead time: Stock",
            attachments=["cert_8130.pdf"],
        )

        self.service.record_client_quote(
            client_email="delta@example.com",
            client_name="Delta Tech",
            company_name="Delta Airlines",
            quote_number="QTE-DELTA-002",
            rfq_id="RFQ-D2",
            part_number="060-1234-00",
            description="Altitude Transceiver Unit",
            quantity=5,
            unit_price=1200.0,
            total_price=6000.0,
            condition="FN",
            certification="OEM CoC",
            lead_time="1-2 Days",
            valid_until="2026-11-20",
            status="Sent",
            sent_at="2026-10-05T15:30:00Z",
            email_subject="Quotation QTE-DELTA-002 - Part Number 060-1234-00",
            email_body="Dear Delta Tech,\nUpdated quote: 060-1234-00 at $1,200.00 each.\nLead time: 1-2 Days",
        )

        self.service.record_client_quote(
            client_email="delta@example.com",
            client_name="Delta Tech",
            company_name="Delta Airlines",
            quote_number="QTE-DELTA-003",
            rfq_id="RFQ-D3",
            part_number="B03AA1040",
            description="Fuel Metering Valve",
            quantity=1,
            unit_price=8500.0,
            total_price=8500.0,
            condition="OH",
            certification="EASA Form 1",
            lead_time="3-5 Days",
            valid_until="2026-11-30",
            status="Sent",
            sent_at="2026-10-06T08:00:00Z",
            email_subject="Quotation QTE-DELTA-003 - Part Number B03AA1040",
            email_body="Dear Delta Tech,\nValve quote: B03AA1040 at $8,500.00.\nLead time: 3-5 Days",
        )

        history = self.service.get_client_quote_history("delta@example.com")
        self.assertEqual(history["client_email"], "delta@example.com")
        self.assertEqual(history["company_name"], "Delta Airlines")
        self.assertEqual(history["total_parts_quoted"], 2)
        self.assertEqual(history["total_quotes"], 3)
        self.assertEqual(history["total_quoted_value"], 17000.0)

        # Check part 060123400 history
        part_a = history["parts"]["060123400"]
        self.assertEqual(part_a["times_quoted"], 2)
        self.assertEqual(part_a["latest_unit_price"], 1200.0)
        self.assertEqual(part_a["latest_condition"], "FN")
        self.assertEqual(len(part_a["quotes"]), 2)

        # Check part B03AA1040 history
        part_b = history["parts"]["B03AA1040"]
        self.assertEqual(part_b["times_quoted"], 1)
        self.assertEqual(part_b["latest_unit_price"], 8500.0)

    def test_get_part_quote_history_for_client(self):
        self.service.record_client_quote(
            client_email="buyer@united.example",
            quote_number="QTE-U1",
            part_number="A33965-14",
            unit_price=350.0,
            quantity=4,
            condition="NE",
            sent_at="2026-10-04T12:00:00Z",
        )
        self.service.record_client_quote(
            client_email="buyer@united.example",
            quote_number="QTE-U2",
            part_number="A33965-14",
            unit_price=325.0,
            quantity=10,
            condition="FN",
            sent_at="2026-10-06T09:00:00Z",
        )

        quotes = self.service.get_part_quote_history_for_client("buyer@united.example", "A33965-14")
        self.assertEqual(len(quotes), 2)
        # Ordered by sent_at DESC
        self.assertEqual(quotes[0]["quote_number"], "QTE-U2")
        self.assertEqual(quotes[0]["unit_price"], 325.0)
        self.assertEqual(quotes[1]["quote_number"], "QTE-U1")
        self.assertEqual(quotes[1]["unit_price"], 350.0)

    def test_get_part_all_clients_history(self):
        self.service.record_client_quote(
            client_email="client1@aero.com",
            quote_number="QTE-C1",
            part_number="5-89355-88",
            unit_price=950.0,
            company_name="Client 1 Corp",
        )
        self.service.record_client_quote(
            client_email="client2@aero.com",
            quote_number="QTE-C2",
            part_number="5-89355-88",
            unit_price=1050.0,
            company_name="Client 2 Corp",
        )

        clients = self.service.get_part_all_clients_history("5-89355-88")
        self.assertEqual(len(clients), 2)
        emails = {c["client_email"] for c in clients}
        self.assertIn("client1@aero.com", emails)
        self.assertIn("client2@aero.com", emails)

    def test_list_clients(self):
        self.service.record_client_quote(
            client_email="alpha@test.com",
            quote_number="Q-1",
            part_number="P1",
            unit_price=100.0,
            company_name="Alpha Co",
        )
        self.service.record_client_quote(
            client_email="beta@test.com",
            quote_number="Q-2",
            part_number="P2",
            unit_price=200.0,
            company_name="Beta Co",
        )

        clients = self.service.list_clients()
        self.assertEqual(len(clients), 2)
        filtered = self.service.list_clients(search="Alpha")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["client_email"], "alpha@test.com")

    def test_parse_and_ingest_sent_email(self):
        message = {
            "id": "msg-graph-999",
            "subject": "Quotation QTE-4455 - Part Number 140-810043-12",
            "date": "2026-10-06T09:15:00Z",
            "toRecipients": [{"emailAddress": {"address": "procurement@airways.com", "name": "Airways Sourcing"}}],
            "body": (
                "Dear Airways Sourcing,\n\n"
                "Thank you for contacting Winged Tycoons. We are pleased to offer:\n\n"
                "- Part Number: 140-810043-12\n"
                "- Description: Actuator Motor Assembly\n"
                "- Quantity: 3 EA\n"
                "- Condition: NE\n"
                "- Certification: FAA 8130-3\n"
                "- Unit Price: $3,450.00 USD\n"
                "- Lead Time: Stock\n\n"
                "Kind regards,\nWinged Tycoons"
            ),
        }

        parsed = self.service.parse_and_ingest_sent_email(message)
        self.assertEqual(len(parsed), 1)
        item = parsed[0]
        self.assertEqual(item["client_email"], "procurement@airways.com")
        self.assertEqual(item["part_number"], "140-810043-12")
        self.assertEqual(item["quantity"], 3)
        self.assertEqual(item["unit_price"], 3450.0)
        self.assertEqual(item["total_price"], 10350.0)
        self.assertEqual(item["condition"], "NE")
        self.assertEqual(item["lead_time"], "Stock")

        # Verify it is now immediately in client history
        history = self.service.get_client_quote_history("procurement@airways.com")
        self.assertEqual(history["total_quotes"], 1)
        self.assertIn("14081004312", history["parts"])

    def test_customer_question_service_uses_client_history(self):
        self.service.record_client_quote(
            client_email="pilot@skyways.com",
            quote_number="QTE-SKY-777",
            part_number="060-1234-00",
            quantity=2,
            unit_price=1450.0,
            condition="NE",
            certification="FAA 8130-3",
            lead_time="2 Days",
            sent_at="2026-10-02T11:00:00Z",
        )

        with patch("services.client_history_service.client_history_service", self.service):
            cqs = CustomerQuestionService()
            answer = cqs.answer_from_client_history(
                question="What did you quote me last time for 060-1234-00?",
                client_email="pilot@skyways.com",
                part_number="060-1234-00",
            )
            self.assertIsNotNone(answer)
            self.assertIn("QTE-SKY-777", answer)
            self.assertIn("$1,450.00 USD", answer)
            self.assertIn("FAA 8130-3", answer)
            self.assertIn("2 Days", answer)


if __name__ == "__main__":
    unittest.main()
