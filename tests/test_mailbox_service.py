import unittest
from unittest.mock import Mock, patch

from services.mailbox_service import fetch_inbox_headers, send_message


class MailboxServiceTests(unittest.TestCase):
    @patch("services.mailbox_service._client")
    def test_maps_graph_message_headers(self, client_factory):
        client = Mock()
        client.request.return_value = {
            "value": [{
                "id": "message-1",
                "from": {"emailAddress": {"address": "buyer@example.com"}},
                "subject": "RFQ",
                "receivedDateTime": "2026-09-17T12:00:00Z",
            }]
        }
        client_factory.return_value = client
        self.assertEqual(fetch_inbox_headers("sales"), [{
            "mailbox": "sales",
            "message_id": "message-1",
            "from": "buyer@example.com",
            "subject": "RFQ",
            "date": "2026-09-17T12:00:00Z",
        }])
        client.request.assert_called_once()

    @patch("services.mailbox_service._client")
    def test_sends_text_message_through_graph(self, client_factory):
        client = Mock()
        client_factory.return_value = client
        send_message("purchasing", "supplier@example.com", "Quote", "Please quote.", "message-1")
        client.request.assert_called_once()
        method, path, payload = client.request.call_args.args
        self.assertEqual(("POST", "/users/purchasing@wingedtycoons.com/sendMail"), (method, path))
        self.assertEqual("Please quote.", payload["message"]["body"]["content"])
        self.assertEqual("message-1", payload["message"]["replyTo"][0]["emailAddress"]["address"])

    def test_rejects_unknown_mailbox(self):
        with self.assertRaisesRegex(ValueError, "Unknown mailbox"):
            fetch_inbox_headers("unknown")


if __name__ == "__main__":
    unittest.main()
