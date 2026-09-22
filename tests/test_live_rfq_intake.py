import os
import json
import unittest
from urllib import request as urllib_request
from urllib.error import HTTPError

LIVE_API_URL = os.getenv("LIVE_API_URL", "").rstrip("/")
LIVE_API_TOKEN = os.getenv("LIVE_API_TOKEN", "")


class TestLiveRFQIntake(unittest.TestCase):
    def test_live_aog_rfq_intake_returns_non_failed_status(self):
        if not LIVE_API_URL or not LIVE_API_TOKEN:
            self.skipTest("Set LIVE_API_URL and LIVE_API_TOKEN to run the deployed AOG intake smoke test.")

        payload = {
            "raw_text": (
                "AOG request from Delta MRO Services <procurement@deltamro.com>. "
                "Need part number UNKNOWN-AOG-001, quantity 1, condition NE. "
                "Aircraft on ground in Miami; please expedite."
            ),
            "customer_name": "Synthetic AOG Test Customer",
            "customer_email": "synthetic-aog-test@example.com",
        }
        http_request = urllib_request.Request(
            f"{LIVE_API_URL}/api/rfqs/intake",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {LIVE_API_TOKEN}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(http_request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            self.fail(f"Live RFQ intake returned HTTP {error.code}: {error.read().decode('utf-8')}")

        self.assertIn(
            result["status"],
            {"Pending_Internal_Review", "Intake_Parsed", "Supplier_Request_Sent", "Supplier_Sourcing"},
        )
        self.assertNotEqual(result["status"], "Intake_Failed")
