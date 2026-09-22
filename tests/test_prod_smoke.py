"""Opt-in smoke tests for a deployed production API.

Run with LIVE_API_URL and LIVE_API_TOKEN set. The token must belong to an
internal role permitted to read automation events and submit RFQs.
"""

from __future__ import annotations

import json
import os
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TestProductionSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_url = os.getenv("LIVE_API_URL", "").strip().rstrip("/")
        cls.token = os.getenv("LIVE_API_TOKEN", "").strip()
        if not cls.base_url or not cls.token:
            raise unittest.SkipTest("Set LIVE_API_URL and LIVE_API_TOKEN to run production smoke tests.")

    def request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json", "Authorization": f"Bearer {self.token}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError) as exc:
            self.fail(f"Live request failed for {path}: {exc}")

    def test_ready_reports_healthy_database(self):
        status, payload = self.request("GET", "/ready")
        self.assertEqual(status, 200)
        self.assertEqual(payload.get("status"), "ready")
        self.assertTrue(payload.get("database", {}).get("healthy"))

    def test_automation_events_do_not_return_fallback_warning(self):
        status, payload = self.request("GET", "/api/internal/automation-events")
        self.assertEqual(status, 200)
        serialized = json.dumps(payload).lower()
        self.assertNotIn("frontend_fallback_warning", serialized)
        self.assertNotIn("fallback_warning", serialized)

    def test_aog_intake_does_not_fail(self):
        status, payload = self.request(
            "POST",
            "/api/rfqs/intake",
            {
                "raw_text": "AOG request: please source 060-1234-00 quantity 1 immediately.",
                "customer_name": "Production Smoke Test",
                "customer_email": "smoke-test@example.com",
                "customer_country": "US",
            },
        )
        self.assertIn(status, {200, 201})
        self.assertNotEqual(payload.get("status"), "Intake_Failed")
        self.assertIn(
            payload.get("status"),
            {"Pending_Internal_Review", "Validating", "Inventory_Lookup", "Supplier_Sourcing", "Quote_Generated", "Quote_Sent"},
        )


if __name__ == "__main__":
    unittest.main()
