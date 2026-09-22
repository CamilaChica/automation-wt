import os
import re
from email import policy
from email.parser import BytesParser
from typing import Any, Dict, List

from services.supplier_database import supplier_db
from services.supplier_ingestion_service import SupplierEmailIngestionService


class SupplierEmailLoader:
    def __init__(self):
        self.ingestion_service = SupplierEmailIngestionService()

    def load_raw_email_text(self, raw_email_text: str, mailbox: str = "purchasing", message_id: str | None = None, attachments: list[dict] | None = None) -> Dict[str, Any]:
        normalized = raw_email_text or ""
        normalized = re.sub(r"<br\s*/?>", "\n", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"</?(p|div|tr|td|table|body|html|span|font)[^>]*>", "\n", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"<[^>]+>", " ", normalized, flags=re.IGNORECASE | re.DOTALL)
        normalized = normalized.replace("&nbsp;", " ")
        normalized = normalized.replace("&#65279;", " ")
        normalized = "\n".join(line.strip() for line in normalized.splitlines())
        normalized = re.sub(r"[ \t]+", " ", normalized)
        return self.ingestion_service.ingest_email(normalized, mailbox=mailbox, message_id=message_id, attachments=attachments)

    def load_from_message_bytes(self, raw_message: bytes) -> Dict[str, Any]:
        message = BytesParser(policy=policy.default).parsebytes(raw_message)
        sender = message.get("From", "")
        subject = message.get("Subject", "")
        body = self._extract_body(message)
        email_text = f"From: {sender}\nSubject: {subject}\n\n{body}"
        return self.ingestion_service.ingest_email(email_text)

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
                results.append(self.load_raw_email_text(body))
        return results
