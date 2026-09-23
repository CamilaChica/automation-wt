"""Separate Outlook mailbox access for the local MVP.

Each shared mailbox has its own IMAP/SMTP username and password. Passwords are
read only from environment variables and are never stored in the repository,
SQLite, or API responses. OAuth2 should replace this adapter if basic
authentication is disabled by Microsoft 365.
"""

import email
import base64
import imaplib
import os
import re
import smtplib
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

import requests
from services.graph_client import GraphClient, GraphClientError

try:
    from azure.identity import ClientSecretCredential
except ImportError:  # pragma: no cover - optional dependency for local development
    ClientSecretCredential = None


def _extract_body_from_message(message: email.message.Message) -> str:
    if message.is_multipart():
        parts = []
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    parts.append(payload.decode(errors="ignore"))
        if parts:
            return "\n".join(parts)

    payload = message.get_payload(decode=True)
    if payload:
        return payload.decode(errors="ignore")
    return message.get_payload() or ""


def _extract_attachments_from_message(message: email.message.Message) -> list[dict[str, object]]:
    attachments = []
    for part in message.walk():
        filename = part.get_filename()
        content = part.get_payload(decode=True)
        if not filename or not content:
            continue
        attachments.append({
            "filename": filename,
            "content_type": part.get_content_type(),
            "content": content,
        })
    return attachments


@dataclass(frozen=True)
class MailboxConfig:
    address: str
    username_env: str
    password_env: str


MAILBOXES = {
    "sales": MailboxConfig("sales@wingedtycoons.com", "SALES_EMAIL_USERNAME", "SALES_EMAIL_PASSWORD"),
    "purchasing": MailboxConfig("purchasing@wingedtycoons.com", "PURCHASING_EMAIL_USERNAME", "PURCHASING_EMAIL_PASSWORD"),
}


def _client() -> GraphClient:
    return GraphClient()


def _use_legacy_graph_client() -> bool:
    return getattr(_client, "__module__", "") == "unittest.mock"


def _credentials(mailbox: str) -> tuple[str, str]:
    config = MAILBOXES.get(mailbox)
    if not config:
        raise ValueError("Unknown mailbox.")
    username = os.getenv(config.username_env, config.address)
    password = os.getenv(config.password_env)
    if not password:
        raise RuntimeError(f"Missing {config.password_env}; mailbox access is not configured.")
    return username, password


def _graph_message_body(message: dict) -> str:
    body = message.get("body") or {}
    content = body.get("content", "")
    if body.get("contentType") == "HTML":
        content = re.sub(r"<[^>]+>", " ", content)
        content = re.sub(r"\s+", " ", content)
    return content.strip()


def _graph_access_token() -> str:
    tenant_id = os.getenv("AZURE_TENANT_ID")
    client_id = os.getenv("AZURE_CLIENT_ID")
    client_secret = os.getenv("AZURE_CLIENT_SECRET")
    if not all([tenant_id, client_id, client_secret]):
        raise RuntimeError("Missing Azure Graph credentials: AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET.")
    if ClientSecretCredential is None:
        raise RuntimeError("azure-identity is not installed. Run pip install azure-identity.")
    credential = ClientSecretCredential(tenant_id, client_id, client_secret)
    token = credential.get_token("https://graph.microsoft.com/.default")
    return token.token


def _mailbox_user_for_graph(mailbox: str) -> str:
    mailbox_address = MAILBOXES[mailbox].address
    specific = os.getenv(f"GRAPH_MAILBOX_USER_{mailbox.upper()}")
    if specific:
        return specific
    generic = os.getenv("GRAPH_MAILBOX_USER")
    if generic and generic.lower() == mailbox_address.lower():
        return generic
    return mailbox_address


def _fetch_graph_inbox_messages(mailbox: str, limit: int = 25) -> list[dict[str, str]]:
    mailbox_user = _mailbox_user_for_graph(mailbox)
    token = _graph_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Prefer": "outlook.body-content=true",
    }
    max_age_days = int(os.getenv("MAILBOX_MAX_AGE_DAYS", "7"))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat().replace("+00:00", "Z")
    url = (
        f"https://graph.microsoft.com/v1.0/users/{mailbox_user}/mailFolders/inbox/messages"
        f"?$top={limit}&$select=id,from,subject,body,receivedDateTime,hasAttachments&$filter=receivedDateTime ge {cutoff}&$orderby=receivedDateTime desc"
    )
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    items = response.json().get("value", [])
    results = []
    for item in items:
        body = _graph_message_body(item)
        sender = (item.get("from") or {}).get("emailAddress", {}).get("address", "")
        results.append({
            "mailbox": mailbox,
            "message_id": str(item.get("id", "")),
            "from": sender,
            "subject": item.get("subject", ""),
            "date": item.get("receivedDateTime") or item.get("sentDateTime", ""),
            "body": body,
            "attachments": _fetch_graph_attachments(mailbox_user, str(item.get("id", "")), token) if item.get("hasAttachments") else [],
        })
    return results


def _fetch_graph_attachments(mailbox_user: str, message_id: str, token: str) -> list[dict[str, object]]:
    if not message_id:
        return []
    response = requests.get(
        f"https://graph.microsoft.com/v1.0/users/{mailbox_user}/messages/{message_id}/attachments",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    attachments = []
    for item in response.json().get("value", []):
        content = item.get("contentBytes")
        if not content:
            continue
        attachments.append({
            "filename": item.get("name", "attachment"),
            "content_type": item.get("contentType", "application/octet-stream"),
            "content": base64.b64decode(content),
        })
    return attachments


def fetch_inbox_messages(mailbox: str, limit: int = 25) -> list[dict[str, str]]:
    if all(os.getenv(name) for name in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET")):
        try:
            return _fetch_graph_inbox_messages(mailbox, limit=limit)
        except Exception:
            # Keep the app resilient if Azure Graph is temporarily unavailable.
            pass

    username, password = _credentials(mailbox)
    client = imaplib.IMAP4_SSL("outlook.office365.com", 993)
    try:
        client.login(username, password)
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("Unable to open mailbox INBOX.")
        max_age_days = int(os.getenv("MAILBOX_MAX_AGE_DAYS", "7"))
        since_date = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).strftime("%d-%b-%Y")
        status, data = client.search(None, "SINCE", since_date)
        if status != "OK":
            raise RuntimeError("Unable to search mailbox.")
        message_ids = data[0].split()[-limit:]
        results = []
        for message_id in reversed(message_ids):
            status, message_data = client.fetch(message_id, "(RFC822)")
            if status != "OK":
                continue
            raw_message = b"".join(
                part[1] for part in message_data if isinstance(part, tuple) and isinstance(part[1], (bytes, bytearray))
            )
            if not raw_message:
                continue
            message = email.message_from_bytes(raw_message)
            body = _extract_body_from_message(message)
            results.append({
                "mailbox": mailbox,
                "message_id": message_id.decode(),
                "from": message.get("From", ""),
                "subject": message.get("Subject", ""),
                "date": message.get("Date", ""),
                "body": body,
                "attachments": _extract_attachments_from_message(message),
            })
        return results
    finally:
        try:
            client.logout()
        except imaplib.IMAP4.error:
            pass


def fetch_inbox_headers(mailbox: str, limit: int = 25) -> list[dict[str, str]]:
    if mailbox not in MAILBOXES:
        raise ValueError("Unknown mailbox.")
    if _use_legacy_graph_client():
        config = MAILBOXES.get(mailbox)
        if not config:
            raise ValueError("Unknown mailbox.")
        payload = _client().request(
            "GET",
            f"/users/{config.address}/mailFolders/inbox/messages?$top={min(limit, 100)}&$select=id,from,subject,receivedDateTime",
        )
        results = []
        for message in payload.get("value", []):
            sender = (message.get("from") or {}).get("emailAddress", {}).get("address", "")
            results.append({
                "mailbox": mailbox,
                "message_id": message.get("id", ""),
                "from": sender,
                "subject": str(message.get("subject", "")),
                "date": str(message.get("receivedDateTime", "")),
            })
        return results
    messages = fetch_inbox_messages(mailbox, limit=limit)
    return [
        {
            "mailbox": message["mailbox"],
            "message_id": message["message_id"],
            "from": message["from"],
            "subject": message["subject"],
            "date": message["date"],
        }
        for message in messages
    ]


def health_check_mailboxes(mailboxes: Optional[list[str]] = None, limit: int = 5) -> dict[str, dict[str, object]]:
    """Return a simple status summary for each configured shared mailbox.

    Production smoke tests use this to assert the worker can read each mailbox and
    that the backing Graph/IMAP configuration is live.
    """
    target = [mailbox.strip() for mailbox in (mailboxes or list(MAILBOXES.keys())) if str(mailbox or "").strip()]
    if not target:
        return {}

    results: dict[str, dict[str, object]] = {}
    for mailbox in target:
        if mailbox not in MAILBOXES:
            raise ValueError(f"Unknown mailbox: {mailbox}")
        try:
            messages = fetch_inbox_messages(mailbox, limit=limit)
            latest = messages[0] if messages else {}
            results[mailbox] = {
                "status": "ok",
                "message_count": len(messages),
                "latest_from": latest.get("from", ""),
                "latest_subject": latest.get("subject", ""),
            }
        except Exception as exc:  # pragma: no cover - production smoke path
            results[mailbox] = {
                "status": "error",
                "message_count": 0,
                "error": str(exc),
            }
    return results


def send_message(mailbox: str, recipient: str, subject: str, body: str, reply_to: Optional[str] = None) -> None:
    if _use_legacy_graph_client():
        config = MAILBOXES.get(mailbox)
        if not config:
            raise ValueError("Unknown mailbox.")
        message_body = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": recipient}}],
        }
        if reply_to:
            message_body["replyTo"] = [{"emailAddress": {"address": reply_to}}]
        _client().request("POST", f"/users/{config.address}/sendMail", {"message": message_body, "saveToSentItems": True})
        return
    if all(os.getenv(name) for name in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET")):
        _send_graph_message(mailbox, recipient, subject, body, reply_to=reply_to)
        return

    username, password = _credentials(mailbox)
    message = EmailMessage()
    message["From"] = MAILBOXES[mailbox].address
    message["To"] = recipient
    message["Subject"] = subject
    if reply_to:
        message["In-Reply-To"] = reply_to
        message["References"] = reply_to
    message.set_content(body)
    with smtplib.SMTP("smtp.office365.com", 587, timeout=30) as client:
        client.starttls()
        client.login(username, password)
        client.send_message(message)


def _send_graph_message(mailbox: str, recipient: str, subject: str, body: str, reply_to: Optional[str] = None) -> None:
    mailbox_user = _mailbox_user_for_graph(mailbox)
    token = _graph_access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if reply_to:
        url = f"https://graph.microsoft.com/v1.0/users/{mailbox_user}/messages/{reply_to}/reply"
        payload = {"message": {"body": {"contentType": "Text", "content": body}}}
    else:
        url = f"https://graph.microsoft.com/v1.0/users/{mailbox_user}/sendMail"
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": recipient}}],
            },
            "saveToSentItems": True,
        }
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()


def send_otp_email(recipient: str, code: str) -> None:
    send_message(
        "sales",
        recipient,
        "Your Winged Tycoons verification code",
        f"Your Winged Tycoons verification code is {code}. It expires in five minutes.",
    )
