import json
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from services.graph_client import GraphClient, GraphClientError, GraphSettings


class FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._payload


class GraphClientTests(unittest.TestCase):
    def settings(self):
        return GraphSettings("tenant", "client", "secret", timeout_seconds=3)

    def test_caches_token_and_requests_graph(self):
        responses = iter([
            FakeResponse({"access_token": "token", "expires_in": 3600}),
            FakeResponse({"value": []}),
            FakeResponse({"value": []}),
        ])
        with patch("services.graph_client.urlopen", side_effect=lambda *_args, **_kwargs: next(responses)) as opener:
            client = GraphClient(self.settings())
            client.request("GET", "/users/sales/messages")
            client.request("GET", "/users/sales/messages")
        self.assertEqual(opener.call_count, 3)

    def test_refreshes_token_after_authentication_failure(self):
        auth_error = HTTPError(
            "https://graph.microsoft.com", 401, "Unauthorized",
            {}, BytesIO(b'{"error":{"code":"InvalidAuthenticationToken"}}'),
        )
        responses = iter([
            FakeResponse({"access_token": "old", "expires_in": 3600}),
            auth_error,
            FakeResponse({"access_token": "new", "expires_in": 3600}),
            FakeResponse({"value": []}),
        ])
        with patch("services.graph_client.urlopen", side_effect=lambda *_args, **_kwargs: next(responses)):
            self.assertEqual(GraphClient(self.settings()).request("GET", "/users/sales/messages"), {"value": []})

    def test_rejects_malformed_token_response(self):
        with patch("services.graph_client.urlopen", return_value=FakeResponse({"expires_in": 3600})):
            with self.assertRaisesRegex(GraphClientError, "access_token"):
                GraphClient(self.settings()).request("GET", "/users/sales/messages")

    def test_requires_all_graph_settings(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(GraphClientError, "AZURE_TENANT_ID"):
                GraphSettings.from_environment()

    def test_surfaces_timeout_or_network_failure(self):
        with patch("services.graph_client.urlopen", side_effect=URLError("offline")):
            with self.assertRaisesRegex(GraphClientError, "timed out or was unreachable"):
                GraphClient(self.settings()).request("GET", "/users/sales/messages")


if __name__ == "__main__":
    unittest.main()
