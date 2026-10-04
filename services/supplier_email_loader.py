from email import policy
from email.parser import BytesParser
from datetime import datetime
from typing import Any, Dict, List

from services.inbound_email_archive import _received_at
from services.supplier_ingestion_service import SupplierEmailIngestionService


class SupplierEmailLoader:
    def __init__(self):
        self.ingestion_service = SupplierEmailIngestionService()

    def load_raw_email_text(self, raw_email_text: str, mailbox: str = "purchasing", message_id: str | None = None, attachments: list[dict] | None = None, source_received_at: datetime | None = None) -> Dict[str, Any]:
        return self.ingestion_service.ingest_email(
            raw_email_text or "",
            mailbox=mailbox,
            message_id=message_id,
            attachments=attachments,
            source_received_at=source_received_at,
        )

    def load_from_message_bytes(self, raw_message: bytes) -> Dict[str, Any]:
        message = BytesParser(policy=policy.default).parsebytes(raw_message)
        sender = message.get("From", "")
        subject = message.get("Subject", "")
        body = self._extract_body(message)
        email_text = f"From: {sender}\nSubject: {subject}\n\n{body}"
        from services.mailbox_service import _extract_attachments_from_message

        return self.ingestion_service.ingest_email(
            email_text,
            attachments=_extract_attachments_from_message(message),
            message_id=str(message.get("Message-ID") or "").strip() or None,
            source_received_at=_received_at(message.get("Date")),
        )

    def _extract_body(self, message) -> str:
        if message.is_multipart():
            parts = []
            for part in message.iter_parts():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        parts.append(payload.decode(errors="ignore"))
            return "\n".join(parts)
        payload = message.get_payload(decode=True)
        if payload:
            return payload.decode(errors="ignore")
        return message.get_payload() or ""

    def load_unread_mailbox_messages(self, mailbox: str, messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        results = []
        for msg in messages:
            body = msg.get("body", "")
            if body:
                results.append(self.load_raw_email_text(
                    body,
                    mailbox=mailbox,
                    message_id=msg.get("message_id"),
                    source_received_at=_received_at(msg.get("date")),
                ))
        return results
