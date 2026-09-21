import asyncio
import os
import unittest
from unittest.mock import patch

from agents.supplier_discovery_agent import SupplierDiscoveryAgent
from agents.customer_communication_agent import CustomerCommunicationAgent
from services.db_service import db_service
from services.mailbox_service import fetch_inbox_messages
from services.supplier_ingestion_service import SupplierEmailIngestionService
from services.communication_service import CommunicationService
from services.supplier_email_extractor import SupplierEmailExtractor
from services.supplier_database import supplier_db


class TestSupplierEmailIngestion(unittest.TestCase):
    def setUp(self):
        self._email_send_enabled = os.environ.get("EMAIL_SEND_ENABLED")
        self._graph_environment = {
            name: os.environ.get(name)
            for name in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "GRAPH_MAILBOX_USER")
        }
        os.environ["EMAIL_SEND_ENABLED"] = "false"
        for name in self._graph_environment:
            os.environ.pop(name, None)
        db_service.reset_supplier_data()

    def tearDown(self):
        if self._email_send_enabled is None:
            os.environ.pop("EMAIL_SEND_ENABLED", None)
        else:
            os.environ["EMAIL_SEND_ENABLED"] = self._email_send_enabled
        for name, value in self._graph_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_ingest_supplier_email_stores_real_offer_data(self):
        email_text = """
        From: quotes@apexaero.com
        Subject: Quote for 060-1234-00

        Apex Aero Components LLC
        We can supply 060-1234-00 quantity 10 at $1,100.00 each.
        FAA 8130-3 certificate included. Lead time 3 days.
        """

        service = SupplierEmailIngestionService()
        result = service.ingest_email(email_text)

        self.assertTrue(result["success"])
        offers = db_service.get_supplier_offers_for_part("060-1234-00")
        self.assertGreater(len(offers), 0)
        self.assertEqual(offers[0]["supplier_name"], "Apex Aero Components LLC")
        self.assertEqual(offers[0]["part_number"], "060-1234-00")
        self.assertEqual(offers[0]["unit_cost"], 1100.0)

    def test_supplier_discovery_reads_persistent_supplier_records(self):
        db_service.save_supplier_offer(
            supplier_name="Vanguard Spares",
            supplier_email="procurement@vanguardspares.com",
            part_number="060-1234-00",
            quantity_available=3,
            unit_cost=1050.0,
            certificate_type="FAA 8130-3",
            lead_time_days=7,
            approval_status="Approved",
            condition_code="NE",
        )

        agent = SupplierDiscoveryAgent()
        results = agent.search_suppliers("060-1234-00", 2)

        self.assertTrue(results)
        self.assertEqual(results[0]["supplier_name"], "Vanguard Aviation Spares Inc.")
        self.assertEqual(results[0]["part_number"], "060-1234-00")

    @patch("services.mailbox_service.imaplib.IMAP4_SSL")
    def test_fetch_inbox_messages_returns_full_email_body(self, mock_imap):
        with patch.dict(
            os.environ,
            {
                "PURCHASING_EMAIL_USERNAME": "buyer@wingedtycoons.com",
                "PURCHASING_EMAIL_PASSWORD": "secret",
            },
            clear=False,
        ):
            mock_client = mock_imap.return_value
            mock_client.select.return_value = ("OK", [b"1"])
            mock_client.search.return_value = ("OK", [b"1 2"])
            mock_client.fetch.side_effect = [
                (
                    "OK",
                    [
                        (
                            b"1",
                            b"From: quotes@apexaero.com\r\nSubject: Quote for 060-1234-00\r\n\r\nApex Aero Components LLC\r\nWe can supply 060-1234-00 quantity 10 at $1,100.00 each.\r\nFAA 8130-3 certificate included. Lead time 3 days.\r\n",
                        )
                    ],
                )
            ]

            messages = fetch_inbox_messages("purchasing", limit=1)

            self.assertEqual(len(messages), 1)
            self.assertIn("060-1234-00", messages[0]["body"])
            self.assertIn("$1,100.00", messages[0]["body"])

    @patch("services.mailbox_service.requests.get")
    @patch("services.mailbox_service.ClientSecretCredential")
    def test_fetch_inbox_messages_uses_graph_when_azure_credentials_are_present(self, mock_cred, mock_get):
        mock_cred.return_value.get_token.return_value = type("Token", (), {"token": "graph-token"})()
        mock_get.return_value.json.return_value = {
            "value": [
                {
                    "id": "msg-1",
                    "from": {"emailAddress": {"address": "quotes@apexaero.com"}},
                    "subject": "Quote for 060-1234-00",
                    "sentDateTime": "2026-09-18T00:00:00Z",
                    "body": {"contentType": "text", "content": "Apex Aero Components LLC\nWe can supply 060-1234-00 quantity 10 at $1,100.00 each."},
                }
            ]
        }
        mock_get.return_value.raise_for_status.return_value = None

        with patch.dict(
            os.environ,
            {
                "AZURE_TENANT_ID": "tenant-id",
                "AZURE_CLIENT_ID": "client-id",
                "AZURE_CLIENT_SECRET": "client-secret",
                "GRAPH_MAILBOX_USER": "purchasing@wingedtycoons.com",
            },
            clear=False,
        ):
            messages = fetch_inbox_messages("purchasing", limit=1)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["from"], "quotes@apexaero.com")
        self.assertIn("060-1234-00", messages[0]["body"])
        mock_get.assert_called()
        self.assertIn("receivedDateTime ge", mock_get.call_args.args[0])

    def test_loader_extracts_part_data_from_html_supplier_email(self):
        html_email = """
        From: parts@globalmena.aero
        Subject: Re: Quote Request #21738174 from ( Winged Tycoons )

        <html><body>
        <p>Dear Team,</p>
        <p>Thank you for your inquiry, in response to your RFQ, GLOBAL MENA AEROSPACE is pleased to provide you with the following quote:</p>
        <p>2 - 8020 - 26 HYD FUSE OH 1EA in stock RELEASE TAG 11/24 TRIUMPH ACTUATIONS 8130-3 DUAL 129 FULL TRACE $ 4,800.00EA outright READY TO BE SHIPPED</p>
        </body></html>
        """

        result = SupplierEmailIngestionService().ingest_email(html_email)

        self.assertTrue(result["success"])
        self.assertEqual(result["part_number"], "2-8020-26")
        self.assertAlmostEqual(float(result["unit_cost"]), 4800.0)

    def test_html_metadata_does_not_override_real_part_number(self):
        email_text = """
        From: quotes@example.com
        Subject: Quote
        <meta http-equiv="Content-Type" content="text/html">
        Part Number: 32-11-45-01 Qty 1 at $1200.00. FAA 8130-3 attached.
        """

        result = SupplierEmailIngestionService().ingest_email(email_text)

        self.assertTrue(result["success"])
        self.assertEqual(result["part_number"], "32-11-45-01")

    def test_encoding_metadata_does_not_override_real_part_number(self):
        email_text = """
        From: rfqs@example.com
        Subject: Request for quotation
        Content-Type: text/html; charset=UTF-8
        Please quote part 7013270-983, quantity 2, condition OH.
        """

        result = SupplierEmailIngestionService().ingest_email(email_text)

        self.assertTrue(result["success"])
        self.assertEqual(result["part_number"], "7013270-983")

    def test_opaque_encoded_token_is_not_a_part_number(self):
        email_text = """
        From: rfqs@example.com
        Subject: Request for quotation
        <meta content="2DOICVWUQXKXVMHMWKHH5IZGBN1J4LO-2DVI9GACHOJ2SAQWUWK3TEKTRQDWRBOOHKMXXFSW0NKB5XN0FVKXUICY8Z6RFAMUVCLHJWWOGV3NUVDP">
        Please quote part 32-11-45-01, quantity 1.
        """

        result = SupplierEmailIngestionService().ingest_email(email_text)

        self.assertTrue(result["success"])
        self.assertEqual(result["part_number"], "32-11-45-01")

    def test_partsbase_billing_reference_is_not_a_part_number(self):
        email_text = """
        From: rfqs@partsbase.com
        Subject: Request for quotation RT-PBILL62OMS8D4
        Please quote the requested aircraft component. Reference: RT-PBILL62OMS8D4.
        """

        result = SupplierEmailIngestionService().ingest_email(email_text)

        self.assertFalse(result["success"])
        self.assertIn("part number", result["error"].lower())

    def test_opaque_partsbase_token_does_not_trigger_supplier_dispatch(self):
        email_text = """
        From: rfqs@partsbase.com
        Subject: PartsBase RFQ
        Reference: U7IICFIEFTRKGQ8-XHSGSW
        Please quote the requested component.
        """

        result = SupplierEmailIngestionService().ingest_email(email_text)

        self.assertFalse(result["success"])

    def test_generic_follow_up_messages_are_ignored(self):
        email_text = """
        From: sender@example.com
        Subject: Follow-up

        Feel free to contact us if you need further information.
        """

        result = SupplierEmailIngestionService().ingest_email(email_text)

        self.assertFalse(result["success"])
        self.assertIn("follow-up", result["error"].lower())

    def test_explicit_supplier_company_wins_over_email_chatter(self):
        email_text = """
        From: sales@real-supplier.com
        Subject: Quote for 7013270-983

        Thank you for your inquiry.
        Company: Real Supplier Aerospace LLC
        Part Number: 7013270-983
        Quantity available: 2
        Unit price: $4,700.00
        FAA 8130-3 attached. Lead time: 5 days.
        """

        extracted = SupplierEmailExtractor().extract(email_text)

        self.assertEqual(extracted["supplier_name"], "Real Supplier Aerospace LLC")

    def test_supplier_request_contains_required_quote_fields_and_thread_reference(self):
        service = CommunicationService()

        result = service.request_missing_supplier_fields(
            recipient="sales@real-supplier.com",
            part_number="7013270-983",
            missing_fields=["release certificate and trace documentation", "quote validity or expiration date"],
            reply_to="graph-message-id",
        )

        self.assertEqual(result["transmission_status"], "DRY_RUN")
        self.assertEqual(result["reply_to"], "graph-message-id")
        self.assertIn("certificate", result["body"].lower())
        self.assertIn("same email thread", result["body"].lower())

    def test_customer_follow_up_is_scheduled_once_after_quote(self):
        service = CommunicationService()

        first = service.send_customer_quote(
            recipient="buyer@example.com",
            customer_name="Buyer Company",
            quote_id="QTE-123456",
            quote_summary="Total: $5,000.00",
            reply_to="customer-message-id",
        )
        second = service.schedule_customer_followup(
            recipient="buyer@example.com",
            customer_name="Buyer Company",
            quote_id="QTE-123456",
            reply_to="customer-message-id",
        )

        self.assertEqual(first["transmission_status"], "DRY_RUN")
        self.assertEqual(second["task_key"], "customer-followup:QTE-123456")
        self.assertEqual(second["reply_to"], "customer-message-id")
        self.assertEqual(supplier_db.list_due_communication_tasks("9999-12-31T00:00:00+00:00")[0]["task_type"], "customer_followup")

    @patch.dict(os.environ, {"GRAPH_MAILBOX_USER": "purchasing@wingedtycoons.com", "AZURE_TENANT_ID": "tenant", "AZURE_CLIENT_ID": "client", "AZURE_CLIENT_SECRET": "secret"}, clear=False)
    @patch("services.mailbox_service._graph_access_token")
    @patch("services.mailbox_service.requests.post")
    def test_graph_send_uses_the_correct_shared_mailbox_for_customer_emails(self, mock_post, mock_token):
        from services.mailbox_service import send_message

        mock_token.return_value = "token"
        send_message("sales", "buyer@example.com", "Quote", "Please review the proposal.")

        self.assertIn("sales@wingedtycoons.com", mock_post.call_args.args[0])
        self.assertNotIn("purchasing@wingedtycoons.com", mock_post.call_args.args[0])

    @patch.dict(os.environ, {"EMAIL_SEND_ENABLED": "true"}, clear=False)
    @patch("services.communication_service.send_message")
    def test_customer_quote_email_contains_full_quote_line_items(self, mock_send):
        agent = CustomerCommunicationAgent()
        response = asyncio.run(agent.execute({
            "customer_email": "buyer@example.com",
            "customer_name": "Buyer Company",
            "quote_details": {
                "quote_id": "QTE-123456",
                "total_amount": 4500.0,
                "shipping_cost": 150.0,
                "items": [
                    {"part_number": "060-1234-00", "quantity": 2, "unit_price": 2100.0},
                    {"part_number": "123-9999-00", "quantity": 1, "unit_price": 300.0},
                ],
            },
            "reply_to": "thread-1",
        }))

        self.assertTrue(response.success)
        self.assertIn("060-1234-00", response.data["formatted_body"])
        self.assertIn("$2,100.00", response.data["formatted_body"])
        self.assertEqual("sales", mock_send.call_args.args[0])
        self.assertEqual("buyer@example.com", mock_send.call_args.args[1])

    def test_supplier_discount_request_is_bounded_and_polite(self):
        service = CommunicationService()

        task = service.schedule_supplier_discount_request(
            recipient="sales@supplier.com",
            supplier_name="Supplier Aerospace",
            part_number="7013270-983",
            unit_cost=47000.0,
            source_email_id="EMAIL-1",
            reply_to="supplier-message-id",
        )
        limited = service.schedule_supplier_discount_request(
            recipient="sales@supplier.com",
            supplier_name="Supplier Aerospace",
            part_number="7013270-983",
            unit_cost=47000.0,
            source_email_id="EMAIL-1",
            round_number=3,
        )

        self.assertEqual(task["task_type"], "supplier_discount_request")
        self.assertEqual(task["reply_to"], "supplier-message-id")
        self.assertIn("best possible net price", task["body"])
        self.assertEqual(limited["status"], "LIMIT_REACHED")


if __name__ == "__main__":
    unittest.main()
