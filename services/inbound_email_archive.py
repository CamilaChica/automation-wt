"""Archive inbound email payload and transport metadata before processing."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from services.operations_store import operations_store

logger = logging.getLogger(__name__)


def _received_at(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(str(value))
        except (TypeError, ValueError):
            return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def archive_inbound_message(message: dict[str, Any], mailbox: str, *, processing_status: str = "received") -> None:
    provider_message_id = str(message.get("message_id") or "").strip()
    if not provider_message_id:
        return
    attachment_metadata = [
        {
            "filename": str(item.get("filename") or "attachment"),
            "content_type": str(item.get("content_type") or "application/octet-stream"),
            "size": len(item.get("content") or b""),
        }
        for item in message.get("attachments") or []
    ]
    try:
        operations_store.save_raw_email(
            mailbox=mailbox,
            provider_message_id=provider_message_id,
            internet_message_id=message.get("internet_message_id"),
            conversation_id=message.get("conversation_id"),
            sender=str(message.get("from") or "") or None,
            subject=str(message.get("subject") or "") or None,
            received_at=_received_at(message.get("date")),
            body=str(message.get("body") or ""),
            raw_mime=message.get("raw_mime"),
            headers=message.get("headers") or [],
            attachments=attachment_metadata,
            processing_status=processing_status,
        )
    except Exception:
        logger.exception("Unable to archive inbound message mailbox=%s message=%s", mailbox, provider_message_id)