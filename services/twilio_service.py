"""Twilio SMS notifications with deterministic dry-run behavior."""

from __future__ import annotations

import os
import re
from typing import Any, Dict

import requests

from services.operations_store import operations_store


class TwilioService:
    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        self.from_number = os.getenv("TWILIO_FROM_PHONE_NUMBER", os.getenv("TWILIO_FROM_NUMBER", "")).strip()
        self.enabled = os.getenv("TWILIO_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.base_url = os.getenv("TWILIO_BASE_URL", "https://api.twilio.com/2010-04-01").rstrip("/")

    def send_sms(self, recipient: str, body: str) -> Dict[str, Any]:
        self._validate_phone(recipient)
        message = str(body or "").strip()
        if not message:
            raise ValueError("SMS body cannot be empty.")

        result: Dict[str, Any] = {
            "provider": "twilio",
            "recipient": recipient,
            "body": message,
            "status": "DRY_RUN",
        }
        if not self.enabled:
            result["communication_id"] = self._record_dispatch(recipient, message, result["status"])
            return result

        if not self.account_sid or not self.auth_token or not self.from_number:
            raise RuntimeError(
                "TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_PHONE_NUMBER are required when Twilio is enabled."
            )
        self._validate_phone(self.from_number)
        response = requests.post(
            f"{self.base_url}/Accounts/{self.account_sid}/Messages.json",
            data={"To": recipient, "From": self.from_number, "Body": message},
            auth=(self.account_sid, self.auth_token),
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        result.update({"status": "SENT", "message_id": payload.get("sid"), "provider_response": payload})
        result["communication_id"] = self._record_dispatch(recipient, message, result["status"])
        return result

    def send_shipment_update(self, recipient: str, shipment_id: str, status: str, tracking_url: str | None = None) -> Dict[str, Any]:
        message = f"Winged Tycoons shipment {shipment_id}: {status}."
        if tracking_url:
            message = f"{message} Track: {tracking_url}"
        return self.send_sms(recipient, message)

    @staticmethod
    def _validate_phone(value: str) -> None:
        if not re.fullmatch(r"\+[1-9]\d{7,14}", str(value or "").strip()):
            raise ValueError("Phone numbers must use E.164 format, for example +13055550142.")

    def _record_dispatch(self, recipient: str, body: str, status: str) -> str:
        communication_id = operations_store.record_communication(
            entity_type="sms",
            entity_id=recipient,
            recipient=recipient,
            sender=self.from_number or "twilio",
            channel="sms",
            subject="Winged Tycoons SMS notification",
            message=body,
            message_type="outbound",
            status=status,
        )
        operations_store.record_automation_event(
            event_type="sms_dispatch",
            entity_type="sms",
            entity_id=communication_id,
            status=status,
            result="Twilio dispatch recorded",
        )
        return communication_id


twilio_service = TwilioService()
