"""Replay an AfterShip-style signed webhook against a local or public API."""

import base64
import hashlib
import hmac
import json
import os
import sys
from urllib.request import Request, urlopen

from dotenv import load_dotenv


ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"), override=True)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/test_carrier_webhook.py <webhook-url>")
    webhook_url = sys.argv[1]
    secret = os.getenv("CARRIER_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise SystemExit("CARRIER_WEBHOOK_SECRET is required")

    payload = {
        "event": "tracking_update",
        "msg": {
            "slug": "fedex",
            "tracking_number": "LOCAL-TEST-123",
            "tag": "InTransit",
            "checkpoints": [{
                "location": "Memphis, TN",
                "message": "Departed carrier facility",
            }],
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    request = Request(
        webhook_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "aftership-hmac-sha256": signature,
        },
    )
    with urlopen(request, timeout=30) as response:
        print(f"WEBHOOK_STATUS={response.status}")
        print(response.read().decode())


if __name__ == "__main__":
    main()
