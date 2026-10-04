"""Opt-in end-to-end check against an isolated staging deployment.

The submitted RFQ runs through the deployed API and background workers. Add
only staging customer and supplier inboxes to STAGING_EMAIL_ALLOWLIST; all
other recipients are blocked when messages are queued or dispatched. The
configured test part must have an approved, traceable supplier offer that can
be quoted automatically under the staging pricing policy.
"""

from __future__ import annotations

import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pytest


pytestmark = pytest.mark.staging


def _staging_config() -> tuple[str, str, str, str, int]:
    base_url = os.getenv("STAGING_API_URL", "").strip().rstrip("/")
    token = os.getenv("STAGING_API_TOKEN", "").strip()
    test_email = os.getenv("STAGING_TEST_EMAIL", "").strip().lower()
    allowed_emails = {
        address.strip().lower()
        for address in os.getenv("STAGING_EMAIL_ALLOWLIST", "").replace(";", ",").split(",")
        if address.strip()
    }
    part_number = os.getenv("STAGING_TEST_PART_NUMBER", "").strip().upper()
    quantity = int(os.getenv("STAGING_TEST_QUANTITY", "1"))

    if not base_url or not token or not test_email or not part_number:
        pytest.skip(
            "Set STAGING_API_URL, STAGING_API_TOKEN, STAGING_TEST_EMAIL, and "
            "STAGING_TEST_PART_NUMBER to run staging integration tests."
        )

    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        pytest.fail("STAGING_API_URL must use HTTPS.")
    if not re.search(r"(^|[.-])(stage|staging|sandbox|test)([.-]|$)", parsed.hostname, re.I):
        pytest.fail("STAGING_API_URL host must be explicitly named stage, staging, sandbox, or test.")
    if test_email not in allowed_emails:
        pytest.fail("STAGING_TEST_EMAIL must also appear in STAGING_EMAIL_ALLOWLIST.")
    if quantity < 1:
        pytest.fail("STAGING_TEST_QUANTITY must be a positive integer.")
    return base_url, token, test_email, part_number, quantity


def _request(
    base_url: str,
    token: str,
    method: str,
    path: str,
    payload: dict | None = None,
) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Authorization": f"******",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(f"{base_url}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            content = response.read().decode("utf-8")
            return response.status, json.loads(content) if content else {}
    except HTTPError as exc:
        content = exc.read().decode("utf-8", errors="replace")
        pytest.fail(f"Staging request {method} {path} returned HTTP {exc.code}: {content}")
    except URLError as exc:
        pytest.fail(f"Staging request {method} {path} failed: {exc.reason}")


def test_staging_api_and_database_are_ready():
    base_url, token, *_ = _staging_config()
    status, payload = _request(base_url, token, "GET", "/ready")

    assert status == 200
    assert payload.get("status") == "ready"
    assert payload.get("database", {}).get("healthy") is True


def test_staging_rfq_reaches_the_real_agent_pipeline():
    base_url, token, test_email, part_number, quantity = _staging_config()
    status, submitted = _request(
        base_url,
        token,
        "POST",
        "/api/rfqs/intake",
        {
            "raw_text": (
                f"STAGING INTEGRATION TEST - do not fulfill. "
                f"Please quote {quantity} units of part number {part_number}, "
                "condition NE, FAA 8130-3 required. Test request only."
            ),
            "customer_name": "Winged Tycoons Staging Integration Test",
            "customer_email": test_email,
            "customer_country": "US",
        },
    )
    assert status in {200, 201}
    assert submitted.get("rfq_id")
    assert submitted.get("status") == "Processing_Queued"

    deadline = time.monotonic() + 180
    detail: dict = {}
    failed_statuses = {
        "Intake_Failed",
        "Pending_Internal_Review",
        "Blocked_Compliance_Review",
        "No_Quote",
    }
    while time.monotonic() < deadline:
        detail_status, detail = _request(
            base_url,
            token,
            "GET",
            f"/api/rfqs/{submitted['rfq_id']}",
        )
        assert detail_status == 200
        rfq = detail.get("rfq") or {}
        if rfq.get("status") == "Quote_Sent":
            break
        if rfq.get("status") in failed_statuses:
            pytest.fail(
                f"Staging RFQ stopped at {rfq['status']}; inspect its audit log before retrying."
            )
        time.sleep(3)
    else:
        pytest.fail(
            f"Staging RFQ did not reach Quote_Sent; last status was "
            f"{(detail.get('rfq') or {}).get('status')!r}."
        )

    rfq = detail.get("rfq") or {}
    logs = detail.get("logs") or []
    agent_names = {entry.get("agent_name") for entry in logs}
    assert rfq.get("id") == submitted["rfq_id"]
    assert rfq.get("status") == "Quote_Sent"
    quote = (detail.get("quote_details") or {}).get("quote") or {}
    assert quote.get("status") == "Sent"
    assert {
        "RFQIntakeAgent",
        "PartsIntelligenceAgent",
        "InventoryAgent",
        "SupplierDiscoveryAgent",
        "ComplianceAgent",
        "PricingAgent",
        "QuoteGenerationAgent",
        "CustomerCommunicationAgent",
    }.issubset(agent_names)
