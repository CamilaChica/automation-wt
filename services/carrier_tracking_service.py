"""Carrier tracking integration with an AfterShip-compatible API."""

import hashlib
import hmac
import os
import base64
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
        self.api_key = api_key or os.getenv("AFTERSHIP_API_KEY", "")
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
