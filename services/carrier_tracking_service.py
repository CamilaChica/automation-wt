"""Carrier tracking integration with an AfterShip-compatible API."""

import hashlib
import hmac
import os
import base64
import json
from typing import Any, Dict, Optional

import requests


STATUS_MAP = {
    "Pending": "Preparing Shipment",
    "InfoReceived": "Label Created",
    "InTransit": "In Transit",
    "OutForDelivery": "Out for Delivery",
    "Delivered": "Delivered",
    "AvailableForPickup": "Ready for Pickup",
    "Exception": "Delivery Exception",
    "FailedAttempt": "Delivery Exception",
    "Expired": "Delivery Exception",
}


class CarrierTrackingService:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = os.getenv("AFTERSHIP_API_KEY", "") if api_key is None else api_key
        self.base_url = (base_url or os.getenv("AFTERSHIP_BASE_URL", "https://api.aftership.com/tracking/2026-07")).rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {
            "as-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    def create_tracker(self, carrier: str, tracking_number: str, title: str = "Winged Tycoons shipment") -> Dict[str, Any]:
        if not self.api_key:
            return {
                "status": "DRY_RUN",
                "carrier": carrier,
                "tracking_number": tracking_number,
            }
        response = requests.post(
            f"{self.base_url}/trackings",
            headers=self._headers(),
            json={
                "tracking_number": tracking_number,
                "slug": carrier.lower(),
                "title": title,
            },
            timeout=30,
        )
        if response.status_code not in (200, 201, 202, 400):
            response.raise_for_status()
        return response.json()

    def get_tracker(self, carrier: str, tracking_number: str) -> Dict[str, Any]:
        if not self.api_key:
            return {"status": "DRY_RUN", "carrier": carrier, "tracking_number": tracking_number}
        response = requests.get(
            f"{self.base_url}/trackings/{carrier.lower()}/{tracking_number}",
            headers=self._headers(),
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _extract_tracking(payload: Dict[str, Any]) -> Dict[str, Any]:
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict):
            trackings = data.get("trackings")
            if isinstance(trackings, list):
                return trackings[0] if trackings else {}
            if isinstance(data.get("tracking"), dict):
                return data["tracking"]
            if data.get("tracking_number"):
                return data
        return {}

    def lookup_live(self, carrier: str, tracking_number: str) -> Optional[Dict[str, Any]]:
        """Fetch live carrier status from AfterShip, registering the number if needed."""
        if not self.api_key:
            return None
        tracking: Dict[str, Any] = {}
        try:
            response = requests.get(
                f"{self.base_url}/trackings",
                headers=self._headers(),
                params={"tracking_numbers": tracking_number},
                timeout=15,
            )
            if response.ok:
                tracking = self._extract_tracking(response.json())
            if not tracking:
                body: Dict[str, Any] = {"tracking_number": tracking_number}
                if carrier:
                    body["slug"] = carrier.lower()
                created = requests.post(f"{self.base_url}/trackings", headers=self._headers(), json=body, timeout=15)
                if created.ok:
                    tracking = self._extract_tracking(created.json())
        except (requests.RequestException, ValueError):
            return None
        if not tracking:
            return None
        checkpoints = tracking.get("checkpoints") or []
        events = [
            {
                "status": self.normalize_status(cp.get("tag")),
                "location": cp.get("location") or ", ".join(filter(None, [cp.get("city"), cp.get("state"), cp.get("country_iso3")])) or None,
                "description": cp.get("message") or "",
                "occurred_at": cp.get("checkpoint_time"),
            }
            for cp in reversed(checkpoints)
        ]
        eta = tracking.get("expected_delivery") or tracking.get("courier_estimated_delivery_date") or tracking.get("aftership_estimated_delivery_date")
        if isinstance(eta, dict):
            eta = eta.get("estimated_delivery_date") or eta.get("estimated_delivery_date_max")
        return {
            "status": self.normalize_status(tracking.get("tag")),
            "carrier": (tracking.get("slug") or carrier or "").upper() or carrier,
            "estimated_delivery": eta,
            "events": events,
        }

    @staticmethod
    def normalize_status(value: Optional[str]) -> str:
        if not value:
            return "Preparing Shipment"
        return STATUS_MAP.get(value, value.replace("_", " ").title())

    @classmethod
    def normalize_webhook(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        tracking = ((payload.get("data") or {}).get("tracking") or payload.get("tracking") or payload.get("msg") or {})
        checkpoints = tracking.get("checkpoints") or []
        latest = checkpoints[-1] if checkpoints else {}
        raw_status = tracking.get("tag") or tracking.get("status") or tracking.get("tag") or latest.get("tag")
        return {
            "event_id": tracking.get("id") or payload.get("event_id") or hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
            "carrier": tracking.get("slug") or tracking.get("carrier") or tracking.get("courier_tracking_link"),
            "tracking_number": tracking.get("tracking_number") or tracking.get("trackingNumber"),
            "status": cls.normalize_status(raw_status),
            "location": latest.get("location") or latest.get("city"),
            "description": latest.get("message") or latest.get("checkpoint_time") or "Carrier status updated.",
            "occurred_at": latest.get("checkpoint_time") or tracking.get("updated_at"),
        }

    @staticmethod
    def verify_webhook(payload_bytes: bytes, signature: Optional[str], secret: Optional[str] = None) -> bool:
        configured_secret = secret or os.getenv("CARRIER_WEBHOOK_SECRET", "")
        if not configured_secret:
            return False
        if not signature:
            return False
        digest = base64.b64encode(hmac.new(configured_secret.encode(), payload_bytes, hashlib.sha256).digest()).decode()
        return hmac.compare_digest(digest, signature)


carrier_tracking_service = CarrierTrackingService()
