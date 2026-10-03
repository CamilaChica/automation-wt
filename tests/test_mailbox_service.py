import unittest
from unittest.mock import Mock, patch

from services.mailbox_service import _send_graph_message, fetch_inbox_headers, send_message


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

    def _graph_patches(self):
        return (
            patch("services.mailbox_service._graph_access_token", return_value="tok"),
            patch("services.mailbox_service._mailbox_user_for_graph", return_value="sales@wingedtycoons.com"),
        )

    def test_graph_reply_uses_outlook_native_reply(self):
        token, user = self._graph_patches()
        with token, user, patch("services.mailbox_service.requests.post") as post:
            post.return_value = Mock(status_code=202)
            self.assertTrue(_send_graph_message("sales", "buyer@example.com", "RFQ 123", "Thanks", reply_to="graph-id-1"))
        post.assert_called_once()
        self.assertTrue(post.call_args.args[0].endswith("/messages/graph-id-1/reply"))
        self.assertEqual("Thanks", post.call_args.kwargs["json"]["comment"])

    def test_graph_reply_falls_back_to_re_subject_when_thread_missing(self):
        token, user = self._graph_patches()
        with token, user, patch("services.mailbox_service.requests.post") as post:
            post.side_effect = [Mock(status_code=404), Mock(status_code=202, raise_for_status=Mock())]
            self.assertFalse(_send_graph_message("sales", "buyer@example.com", "RFQ 123", "Thanks", reply_to="graph-id-1"))
        self.assertTrue(post.call_args.args[0].endswith("/sendMail"))
        self.assertEqual("Re: RFQ 123", post.call_args.kwargs["json"]["message"]["subject"])

    def test_graph_reply_server_error_raises(self):
        token, user = self._graph_patches()
        failing = Mock(status_code=500)
        failing.raise_for_status.side_effect = RuntimeError("graph 500")
        with token, user, patch("services.mailbox_service.requests.post", return_value=failing):
            with self.assertRaises(RuntimeError):
                _send_graph_message("sales", "buyer@example.com", "RFQ 123", "Thanks", reply_to="graph-id-1")

    def test_rejects_unknown_mailbox(self):
        with self.assertRaisesRegex(ValueError, "Unknown mailbox"):
            fetch_inbox_headers("unknown")


if __name__ == "__main__":
    unittest.main()
