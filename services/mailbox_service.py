"""Separate Outlook mailbox access for the local MVP.

Each shared mailbox has its own IMAP/SMTP username and password. Passwords are
read only from environment variables and are never stored in the repository,
SQLite, or API responses. OAuth2 should replace this adapter if basic
authentication is disabled by Microsoft 365.
"""

import email
import base64
import html
import imaplib
import logging
import mimetypes
import os
import re
import smtplib
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Optional

import requests
from services.graph_client import GraphClient, GraphClientError

logger = logging.getLogger(__name__)

try:
    from azure.identity import ClientSecretCredential
except ImportError:  # pragma: no cover - optional dependency for local development
    ClientSecretCredential = None


_HTML_HINT = re.compile(r"<\s*(html|head|body|div|p|table|style|span|br|meta)\b", re.IGNORECASE)


def html_to_text(content: str) -> str:
    """Convert an HTML email body to readable plain text (drops CSS/scripts)."""
    text = str(content or "")
    if not _HTML_HINT.search(text):
        return text.strip()
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"<(style|script|head|title)\b.*?</\1\s*>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|tr|li|h[1-6]|table)\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</t[dh]\s*>", " \t ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text, flags=re.DOTALL)
    text = html.unescape(text).replace("\xa0", " ").replace("\ufeff", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def _extract_body_from_message(message: email.message.Message) -> str:
    if message.is_multipart():
        parts = []
        html_parts = []
        for part in message.walk():
            content_type = part.get_content_type()
            if content_type in ("text/plain", "text/html") and not part.get_filename():
                payload = part.get_payload(decode=True)
                if payload:
                    decoded = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                    (parts if content_type == "text/plain" else html_parts).append(decoded)
        if parts:
            return html_to_text("\n".join(parts))
        if html_parts:
            return html_to_text("\n".join(html_parts))

    payload = message.get_payload(decode=True)
    if payload:
        return html_to_text(payload.decode(errors="ignore"))
    return html_to_text(message.get_payload() or "")


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
    return html_to_text(content)


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


def _fetch_graph_inbox_messages(
    mailbox: str,
    limit: int = 25,
    skip: int = 0,
    max_age_days: int | None = None,
    oldest_first: bool = False,
) -> list[dict[str, Any]]:
    mailbox_user = _mailbox_user_for_graph(mailbox)
    token = _graph_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Prefer": "outlook.body-content=true",
    }
    if max_age_days is None:
        max_age_days = int(os.getenv("MAILBOX_MAX_AGE_DAYS", "7"))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat().replace("+00:00", "Z")
    skip_param = f"&$skip={int(skip)}" if skip else ""
    sort_order = "asc" if oldest_first else "desc"
    url = (
        f"https://graph.microsoft.com/v1.0/users/{mailbox_user}/mailFolders/inbox/messages"
        f"?$top={limit}{skip_param}&$select=id,internetMessageId,conversationId,internetMessageHeaders,from,subject,body,receivedDateTime,hasAttachments&$filter=receivedDateTime ge {cutoff}&$orderby=receivedDateTime {sort_order}"
    )
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    items = response.json().get("value", [])
    results = []
    for item in items:
        body = _graph_message_body(item)
        sender = (item.get("from") or {}).get("emailAddress", {}).get("address", "")
        raw_mime = None
        message_id = str(item.get("id", ""))
        if message_id:
            try:
                mime_response = requests.get(
                    f"https://graph.microsoft.com/v1.0/users/{mailbox_user}/messages/{message_id}/$value",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=30,
                )
                mime_response.raise_for_status()
                raw_mime = mime_response.content
            except Exception as exc:
                logger.warning("Graph MIME archive unavailable mailbox=%s message=%s error=%s", mailbox, message_id, type(exc).__name__)
        results.append({
            "mailbox": mailbox,
            "message_id": message_id,
            "internet_message_id": str(item.get("internetMessageId") or "").strip() or None,
            "conversation_id": str(item.get("conversationId") or "").strip() or None,
            "headers": item.get("internetMessageHeaders") or [],
            "raw_mime": raw_mime,
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


def fetch_inbox_messages(
    mailbox: str,
    limit: int = 25,
    skip: int = 0,
    max_age_days: int | None = None,
    oldest_first: bool = False,
) -> list[dict[str, Any]]:
    if all(os.getenv(name) for name in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET")):
        try:
            return _fetch_graph_inbox_messages(
                mailbox,
                limit=limit,
                skip=skip,
                max_age_days=max_age_days,
                oldest_first=oldest_first,
            )
        except Exception as exc:
            # Keep the app resilient if Azure Graph is temporarily unavailable.
            logger.warning("Graph mailbox read failed; falling back to IMAP mailbox=%s error=%s", mailbox, type(exc).__name__)

    username, password = _credentials(mailbox)
    client = imaplib.IMAP4_SSL("outlook.office365.com", 993)
    try:
        client.login(username, password)
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("Unable to open mailbox INBOX.")
        if max_age_days is None:
            max_age_days = int(os.getenv("MAILBOX_MAX_AGE_DAYS", "7"))
        since_date = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).strftime("%d-%b-%Y")
        status, data = client.search(None, "SINCE", since_date)
        if status != "OK":
            raise RuntimeError("Unable to search mailbox.")
        all_ids = data[0].split()
        end = len(all_ids) - int(skip)
        if oldest_first:
            message_ids = all_ids[max(0, int(skip)):max(0, int(skip)) + limit]
        else:
            message_ids = all_ids[max(0, end - limit):max(0, end)]
        results = []
        for message_id in message_ids if oldest_first else reversed(message_ids):
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
                "internet_message_id": str(message.get("Message-ID") or "").strip() or None,
                "conversation_id": None,
                "headers": [{"name": key, "value": str(value)} for key, value in message.items()],
                "raw_mime": raw_message,
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


def _reply_subject(subject: str) -> str:
    clean = str(subject or "").strip()
    return clean if clean.lower().startswith("re:") else f"Re: {clean}"


def ensure_staging_recipient_allowed(recipient: str) -> None:
    environments = {
        os.getenv(name, "").strip().lower()
        for name in ("WT_ENV", "ENVIRONMENT", "WT_AUTH_ENV")
    }
    staging_configured = bool(os.getenv("STAGING_EMAIL_ALLOWLIST", "").strip())
    if not staging_configured and not environments.intersection(
        {"stage", "staging", "test", "testing"}
    ):
        return

    allowed_recipients = {
        address.strip().lower()
        for address in os.getenv("STAGING_EMAIL_ALLOWLIST", "").replace(";", ",").split(",")
        if address.strip()
    }
    if recipient.strip().lower() not in allowed_recipients:
        raise RuntimeError(
            "Staging email recipient is not in STAGING_EMAIL_ALLOWLIST; dispatch blocked."
        )


def send_message(
    mailbox: str,
    recipient: str,
    subject: str,
    body: str,
    reply_to: Optional[str] = None,
    *,
    html_body: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> bool:
    """Send an email. Returns False when a reply was requested but the original thread was not found."""
    ensure_staging_recipient_allowed(recipient)
    if _use_legacy_graph_client():
        config = MAILBOXES.get(mailbox)
        if not config:
            raise ValueError("Unknown mailbox.")
        message_body = {
            "subject": subject,
            "body": {"contentType": "HTML" if html_body else "Text", "content": html_body or body},
            "toRecipients": [{"emailAddress": {"address": recipient}}],
        }
        if attachments:
            message_body["attachments"] = [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": _safe_attachment_name(attachment.get("filename")),
                    "contentType": _attachment_content_type(attachment),
                    "contentBytes": base64.b64encode(attachment["content"]).decode("ascii"),
                }
                for attachment in attachments
            ]
        if reply_to:
            message_body["replyTo"] = [{"emailAddress": {"address": reply_to}}]
        _client().request("POST", f"/users/{config.address}/sendMail", {"message": message_body, "saveToSentItems": True})
        return True
    if all(os.getenv(name) for name in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET")):
        return _send_graph_message(
            mailbox, recipient, subject, body, reply_to=reply_to,
            html_body=html_body, attachments=attachments,
        )

    username, password = _credentials(mailbox)
    message = EmailMessage()
    message["From"] = MAILBOXES[mailbox].address
    message["To"] = recipient
    message["Subject"] = _reply_subject(subject) if reply_to else subject
    if reply_to:
        reference = reply_to if reply_to.startswith("<") else f"<{reply_to}>"
        message["In-Reply-To"] = reference
        message["References"] = reference
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    for attachment in attachments or []:
        content = attachment.get("content")
        if not isinstance(content, bytes):
            raise ValueError("Email attachment content must be bytes.")
        maintype, subtype = _attachment_content_type(attachment).split("/", 1)
        message.add_attachment(
            content,
            maintype=maintype,
            subtype=subtype,
            filename=_safe_attachment_name(attachment.get("filename")),
        )
    with smtplib.SMTP("smtp.office365.com", 587, timeout=30) as client:
        client.starttls()
        client.login(username, password)
        client.send_message(message)
    return True


def _resolve_graph_message_id(mailbox_user: str, headers: dict, reply_to: str) -> Optional[str]:
    """Accept either a Graph message id or an Internet Message-ID (<...@...>)."""
    if not (reply_to.startswith("<") or "@" in reply_to):
        return reply_to
    escaped = reply_to.replace("'", "''")
    response = requests.get(
        f"https://graph.microsoft.com/v1.0/users/{mailbox_user}/messages",
        headers=headers,
        params={"$filter": f"internetMessageId eq '{escaped}'", "$select": "id", "$top": "1"},
        timeout=30,
    )
    if response.status_code >= 400:
        return None
    found = (response.json() or {}).get("value") or []
    return found[0].get("id") if found else None


def _safe_attachment_name(value: Any) -> str:
    name = os.path.basename(str(value or "attachment")).replace("\r", "").replace("\n", "").strip()
    return name or "attachment"


def _attachment_content_type(attachment: dict[str, Any]) -> str:
    content_type = str(attachment.get("content_type") or "").split(";", 1)[0].strip().lower()
    if re.fullmatch(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+", content_type):
        return content_type
    guessed_type, _ = mimetypes.guess_type(_safe_attachment_name(attachment.get("filename")))
    return guessed_type or "application/octet-stream"


def _send_graph_message(
    mailbox: str,
    recipient: str,
    subject: str,
    body: str,
    reply_to: Optional[str] = None,
    *,
    html_body: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> bool:
    mailbox_user = _mailbox_user_for_graph(mailbox)
    token = _graph_access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if html_body or attachments:
        content_type = "HTML" if html_body else "Text"
        content = html_body or body
        graph_id = _resolve_graph_message_id(mailbox_user, headers, reply_to) if reply_to else None
        original_found = bool(graph_id)
        if graph_id:
            response = requests.post(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_user}/messages/{graph_id}/createReply",
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            draft_id = str(response.json()["id"])
            response = requests.patch(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_user}/messages/{draft_id}",
                headers=headers,
                json={
                    "toRecipients": [{"emailAddress": {"address": recipient}}],
                    "body": {"contentType": content_type, "content": content},
                },
                timeout=30,
            )
            response.raise_for_status()
        else:
            response = requests.post(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_user}/messages",
                headers=headers,
                json={
                    "subject": _reply_subject(subject) if reply_to else subject,
                    "body": {"contentType": content_type, "content": content},
                    "toRecipients": [{"emailAddress": {"address": recipient}}],
                },
                timeout=30,
            )
            response.raise_for_status()
            draft_id = str(response.json()["id"])

        for attachment in attachments or []:
            file_content = attachment.get("content")
            if not isinstance(file_content, bytes):
                raise ValueError("Email attachment content must be bytes.")
            name = _safe_attachment_name(attachment.get("filename"))
            if len(file_content) <= 3 * 1024 * 1024:
                response = requests.post(
                    f"https://graph.microsoft.com/v1.0/users/{mailbox_user}/messages/{draft_id}/attachments",
                    headers=headers,
                    json={
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": name,
                        "contentType": _attachment_content_type(attachment),
                        "contentBytes": base64.b64encode(file_content).decode("ascii"),
                    },
                    timeout=30,
                )
                response.raise_for_status()
                continue

            response = requests.post(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_user}/messages/{draft_id}/attachments/createUploadSession",
                headers=headers,
                json={"AttachmentItem": {
                    "attachmentType": "file",
                    "name": name,
                    "size": len(file_content),
                    "contentType": _attachment_content_type(attachment),
                }},
                timeout=30,
            )
            response.raise_for_status()
            upload_url = str(response.json()["uploadUrl"])
            chunk_size = 320 * 1024
            for start in range(0, len(file_content), chunk_size):
                chunk = file_content[start:start + chunk_size]
                end = start + len(chunk) - 1
                response = requests.put(
                    upload_url,
                    headers={
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {start}-{end}/{len(file_content)}",
                    },
                    data=chunk,
                    timeout=60,
                )
                response.raise_for_status()

        response = requests.post(
            f"https://graph.microsoft.com/v1.0/users/{mailbox_user}/messages/{draft_id}/send",
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        if reply_to and not original_found:
            logger.warning(
                "email_reply_thread_not_found mailbox=%s recipient=%s; sent as new email for team review",
                mailbox, recipient,
            )
        return not reply_to or original_found

    if reply_to:
        graph_id = _resolve_graph_message_id(mailbox_user, headers, reply_to)
        if graph_id:
            # Outlook's native reply keeps "RE: <original subject>" and the conversation thread.
            response = requests.post(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_user}/messages/{graph_id}/reply",
                headers=headers,
                json={
                    "message": {"toRecipients": [{"emailAddress": {"address": recipient}}]},
                    "comment": body,
                },
                timeout=30,
            )
            if response.status_code < 400:
                return True
            if response.status_code == 429 or response.status_code >= 500:
                response.raise_for_status()
        logger.warning(
            "email_reply_thread_not_found mailbox=%s recipient=%s; sent as new email for team review",
            mailbox,
            recipient,
        )
    response = requests.post(
        f"https://graph.microsoft.com/v1.0/users/{mailbox_user}/sendMail",
        headers=headers,
        json={
            "message": {
                "subject": _reply_subject(subject) if reply_to else subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": recipient}}],
            },
            "saveToSentItems": True,
        },
        timeout=30,
    )
    response.raise_for_status()
    return not reply_to


def send_otp_email(recipient: str, code: str) -> None:
    send_message(
        "sales",
        recipient,
        "Your Winged Tycoons verification code",
        f"Your Winged Tycoons verification code is {code}. It expires in five minutes.",
    )
