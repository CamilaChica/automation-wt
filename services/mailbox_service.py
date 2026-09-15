"""Separate Outlook mailbox access for the local MVP.

Each shared mailbox has its own IMAP/SMTP username and password. Passwords are
read only from environment variables and are never stored in the repository,
SQLite, or API responses. OAuth2 should replace this adapter if basic
authentication is disabled by Microsoft 365.
"""

import email
import imaplib
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional


@dataclass(frozen=True)
class MailboxConfig:
    address: str
    username_env: str
    password_env: str


MAILBOXES = {
    "sales": MailboxConfig("sales@wingedtycoons.com", "SALES_EMAIL_USERNAME", "SALES_EMAIL_PASSWORD"),
    "purchasing": MailboxConfig("purchasing@wingedtycoons.com", "PURCHASING_EMAIL_USERNAME", "PURCHASING_EMAIL_PASSWORD"),
}


def _credentials(mailbox: str) -> tuple[str, str]:
    config = MAILBOXES.get(mailbox)
    if not config:
        raise ValueError("Unknown mailbox.")
    username = os.getenv(config.username_env, config.address)
    password = os.getenv(config.password_env)
    if not password:
        raise RuntimeError(f"Missing {config.password_env}; mailbox access is not configured.")
    return username, password


def fetch_inbox_headers(mailbox: str, limit: int = 25) -> list[dict[str, str]]:
    username, password = _credentials(mailbox)
    client = imaplib.IMAP4_SSL("outlook.office365.com", 993)
    try:
        client.login(username, password)
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("Unable to open mailbox INBOX.")
        status, data = client.search(None, "ALL")
        if status != "OK":
            raise RuntimeError("Unable to search mailbox.")
        message_ids = data[0].split()[-limit:]
        results = []
        for message_id in reversed(message_ids):
            status, message_data = client.fetch(message_id, "(BODY.PEEK[HEADER])")
            if status != "OK":
                continue
            raw_header = b"".join(part for part in message_data if isinstance(part, tuple))
            message = email.message_from_bytes(raw_header)
            results.append({
                "mailbox": mailbox,
                "message_id": message_id.decode(),
                "from": message.get("From", ""),
                "subject": message.get("Subject", ""),
                "date": message.get("Date", ""),
            })
        return results
    finally:
        try:
            client.logout()
        except imaplib.IMAP4.error:
            pass


def _extract_text_body(message: email.message.Message) -> str:
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in content_disposition.lower():
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        return ""
    payload = message.get_payload(decode=True) or b""
    charset = message.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def fetch_inbox_messages(mailbox: str, limit: int = 25) -> list[dict[str, str]]:
    username, password = _credentials(mailbox)
    client = imaplib.IMAP4_SSL("outlook.office365.com", 993)
    try:
        client.login(username, password)
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("Unable to open mailbox INBOX.")
        status, data = client.search(None, "ALL")
        if status != "OK":
            raise RuntimeError("Unable to search mailbox.")

        message_ids = data[0].split()[-limit:]
        messages: list[dict[str, str]] = []
        for message_id in reversed(message_ids):
            status, message_data = client.fetch(message_id, "(RFC822)")
            if status != "OK":
                continue
            chunks = [part for part in message_data if isinstance(part, tuple)]
            if not chunks:
                continue
            raw_bytes = b"".join(chunk[1] for chunk in chunks)
            parsed = email.message_from_bytes(raw_bytes)
            text_body = _extract_text_body(parsed)
            messages.append(
                {
                    "mailbox": mailbox,
                    "message_id": message_id.decode(),
                    "from": parsed.get("From", ""),
                    "subject": parsed.get("Subject", ""),
                    "date": parsed.get("Date", ""),
                    "raw_email": raw_bytes.decode("utf-8", errors="replace"),
                    "body_text": text_body,
                }
            )
        return messages
    finally:
        try:
            client.logout()
        except imaplib.IMAP4.error:
            pass


def send_message(mailbox: str, recipient: str, subject: str, body: str, reply_to: Optional[str] = None) -> None:
    username, password = _credentials(mailbox)
    message = EmailMessage()
    message["From"] = MAILBOXES[mailbox].address
    message["To"] = recipient
    message["Subject"] = subject
    if reply_to:
        message["In-Reply-To"] = reply_to
    message.set_content(body)
    with smtplib.SMTP("smtp.office365.com", 587, timeout=30) as client:
        client.starttls()
        client.login(username, password)
        client.send_message(message)


def send_otp_email(recipient: str, code: str) -> None:
    send_message(
        "sales",
        recipient,
        "Your Winged Tycoons verification code",
        f"Your Winged Tycoons verification code is {code}. It expires in five minutes.",
    )
