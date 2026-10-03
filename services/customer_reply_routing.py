"""Route customer email replies to their existing RFQ and answer common policy questions."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

RFQ_REFERENCE = re.compile(r"\bRFQ-[0-9A-F]{6}\b", re.IGNORECASE)
REPLY_SUBJECT = re.compile(r"^\s*(?:re|fw|fwd|aw|r)\s*:", re.IGNORECASE)
CLOSED_STATUSES = {"Rejected"}
QUOTED_STATUSES = {"Quote_Sent", "Pending_PO_Review", "Purchase_Order_Received"}
REPLY_WINDOW = timedelta(days=45)


def email_derived_name(email: str) -> str:
    return (email or "").split("@", 1)[0].replace(".", " ").title()


def company_name_for_sender(rfqs: Iterable, sender: str) -> str:
    """Prefer a real company name given earlier (e.g. via the portal) over one guessed from the email."""
    sender = (sender or "").lower()
    derived = email_derived_name(sender)
    for rfq in sorted(rfqs, key=lambda r: _created(r), reverse=True):
        name = (getattr(rfq, "customer_name", "") or "").strip()
        if (getattr(rfq, "customer_email", "") or "").lower() == sender and name and "@" not in name and name != derived:
            return name
    return derived


def _created(rfq) -> datetime:
    value = getattr(rfq, "created_at", None)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def find_rfq_for_reply(rfqs: Iterable, sender: str, subject: str, body: str) -> Optional[object]:
    """Return the RFQ an inbound customer email belongs to, or None when it is a new request."""
    sender = (sender or "").lower()
    own = [r for r in rfqs if (getattr(r, "customer_email", "") or "").lower() == sender]
    if not own:
        return None
    own.sort(key=_created, reverse=True)
    references = {ref.upper() for ref in RFQ_REFERENCE.findall(f"{subject or ''}\n{body or ''}")}
    for rfq in own:
        if rfq.id.upper() in references and rfq.status not in CLOSED_STATUSES:
            return rfq
    if REPLY_SUBJECT.match(subject or ""):
        cutoff = datetime.now(timezone.utc) - REPLY_WINDOW
        for rfq in own:
            if rfq.status not in CLOSED_STATUSES and _created(rfq) >= cutoff:
                return rfq
    return next((r for r in own if r.status in QUOTED_STATUSES), None)


def policy_answers(text: str) -> list[str]:
    """Deterministic answers for common sales questions that do not depend on a quote."""
    lowered = (text or "").lower()
    answers = []
    if re.search(r"\bship|shipping|deliver|export|send (?:it|them|the part)|incoterm|freight|courier", lowered):
        answers.append(
            "Shipping: Yes, we ship worldwide, including to your country. Shipping method and cost will be "
            "confirmed with your quotation."
        )
    if re.search(r"8130|easa|form 1|certificat|\bcert\b|trace|paperwork|documentation", lowered):
        answers.append(
            "Certification: Parts are supplied with their available release paperwork (FAA 8130-3 and/or "
            "EASA Form 1 where applicable). The exact certificate for each part will be stated in the quotation."
        )
    if re.search(r"warrant", lowered):
        answers.append(
            "Warranty: Warranty depends on the part condition (e.g. new, overhauled, serviceable) and will be "
            "stated in the quotation. We have noted your warranty requirement."
        )
    if re.search(r"lead time|how long|when|eta|status|update|still waiting|any news", lowered):
        answers.append(
            "Status: Your quotation is in progress; we are checking our inventory and supplier network and "
            "will send it in this same email thread."
        )
    return answers


def build_rfq_update_reply(rfq_id: str, customer_text: str, quote_answer: str | None = None) -> str:
    """Body (without greeting) acknowledging extra details/questions on an existing RFQ."""
    answers = policy_answers(customer_text)
    parts = [f"Thank you for your message regarding your request {rfq_id}. We have added your details to this request."]
    if quote_answer:
        parts.append(quote_answer)
    if answers:
        parts.append("\n".join(f"- {line}" for line in answers))
    if not quote_answer:
        parts.append(
            "Your quotation is being prepared and will be sent in this same email thread. "
            "There is no need to submit a new request."
        )
    parts.append("Best regards,\nWinged Tycoons Sales Team")
    return "\n\n".join(parts)
