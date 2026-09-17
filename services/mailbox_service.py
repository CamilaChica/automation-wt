"""Microsoft Graph mailbox access for the shared sales and purchasing mailboxes."""

from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

from services.graph_client import GraphClient, GraphClientError


@dataclass(frozen=True)
class MailboxConfig:
    address: str


MAILBOXES = {
    "sales": MailboxConfig("sales@wingedtycoons.com"),
    "purchasing": MailboxConfig("purchasing@wingedtycoons.com"),
}


def _mailbox(mailbox: str) -> MailboxConfig:
    config = MAILBOXES.get(mailbox)
    if not config:
        raise ValueError("Unknown mailbox.")
    return config


def _client() -> GraphClient:
    return GraphClient()


def fetch_inbox_headers(mailbox: str, limit: int = 25) -> list[dict[str, str]]:
    config = _mailbox(mailbox)
    if limit <= 0:
        return []
    payload = _client().request(
        "GET",
        f"/users/{config.address}/mailFolders/inbox/messages"
        f"?$top={min(limit, 100)}&$select=id,from,subject,receivedDateTime",
    )
    values = payload.get("value")
    if not isinstance(values, list):
        raise GraphClientError("Microsoft Graph returned an invalid mailbox message list.")
    results = []
    for message in values:
        if not isinstance(message, dict) or not isinstance(message.get("id"), str):
            raise GraphClientError("Microsoft Graph returned an invalid mailbox message.")
        sender = message.get("from", {})
        sender_address = sender.get("emailAddress", {}).get("address", "") if isinstance(sender, dict) else ""
        results.append({
            "mailbox": mailbox,
            "message_id": message["id"],
            "from": sender_address,
            "subject": str(message.get("subject", "")),
            "date": str(message.get("receivedDateTime", "")),
        })
    return results


def send_message(
    mailbox: str,
    recipient: str,
    subject: str,
    body: str,
    reply_to: Optional[str] = None,
) -> None:
    config = _mailbox(mailbox)
    message_body: dict[str, object] = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": recipient}}],
    }
    message: dict[str, object] = {
        "message": message_body,
        "saveToSentItems": True,
    }
    if reply_to:
        message_body["replyTo"] = [{"emailAddress": {"address": reply_to}}]
    _client().request("POST", f"/users/{config.address}/sendMail", message)


def send_otp_email(recipient: str, code: str) -> None:
    send_message(
        "sales",
        recipient,
        "Your Winged Tycoons verification code",
        f"Your Winged Tycoons verification code is {code}. It expires in five minutes.",
    )
