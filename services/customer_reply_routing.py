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


DUPLICATE_REQUEST_WINDOW = timedelta(days=30)
_PN_TOKEN = re.compile(r"\b[A-Z0-9]+(?:-[A-Z0-9]+)+\b", re.IGNORECASE)
_QTY = re.compile(r"\b(?:qty|quantity|qnty)\b\s*[:=#]?\s*(\d{1,6})", re.IGNORECASE)
_NOT_PART_PREFIXES = ("RFQ-", "QTE", "QUOTE", "PO-", "ORDER-", "UTF-", "ISO-")


def normalize_pn(value: str) -> str:
    return re.sub(r"[\s\-]", "", str(value or "")).upper()


def _requested_part_numbers(text: str) -> set[str]:
    found = set()
    for token in _PN_TOKEN.findall(text or ""):
        upper = token.upper()
        if re.search(r"\d", upper) and not upper.startswith(_NOT_PART_PREFIXES) and len(upper) <= 40:
            found.add(normalize_pn(upper))
    return found


def _valid_until(quote) -> Optional[datetime]:
    raw = str(getattr(quote, "valid_until", "") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def find_recent_valid_quote(rfqs: Iterable, quotes: Iterable, items: Iterable, sender: str, text: str,
                            now: Optional[datetime] = None, window: timedelta = DUPLICATE_REQUEST_WINDOW):
    """Return (rfq, quote, matched_items, qty_changed) when every requested P/N already has a valid quote."""
    now = now or datetime.now(timezone.utc)
    sender = (sender or "").lower()
    requested = _requested_part_numbers(text)
    if not sender or not requested:
        return None
    quotes_by_rfq = {getattr(q, "rfq_id", None): q for q in quotes}
    items_by_quote: dict = {}
    for item in items:
        items_by_quote.setdefault(getattr(item, "quote_id", None), []).append(item)
    candidates = [
        r for r in rfqs
        if (getattr(r, "customer_email", "") or "").lower() == sender
        and getattr(r, "status", "") in QUOTED_STATUSES
        and _created(r) >= now - window
    ]
    for rfq in sorted(candidates, key=_created, reverse=True):
        quote = quotes_by_rfq.get(rfq.id)
        valid_until = _valid_until(quote) if quote else None
        if quote is None or valid_until is None or valid_until.date() < now.date():
            continue
        quoted = items_by_quote.get(quote.id, [])
        matched = [i for i in quoted if normalize_pn(i.part_number) in requested]
        if matched and requested <= {normalize_pn(i.part_number) for i in quoted}:
            asked = [int(q) for q in _QTY.findall(text or "")]
            qty_changed = bool(asked) and any(q not in {i.quantity for i in matched} for q in asked)
            return rfq, quote, matched, qty_changed
    return None


def build_resurfaced_quote_text(quote, matched_items, qty_changed: bool) -> str:
    lines = [f"You already have a valid quotation {quote.id} for this request (valid until {quote.valid_until}):"]
    for item in matched_items:
        details = ", ".join(filter(None, [
            f"qty {item.quantity}",
            f"condition {item.condition}" if item.condition else "",
            f"USD {item.unit_price:,.2f} each",
            f"cert {item.certificate_type}" if item.certificate_type else "",
            f"lead time {item.lead_time_days} days" if item.lead_time_days is not None else "",
        ]))
        lines.append(f"- P/N {item.part_number}: {details}")
    if qty_changed:
        lines.append("We have noted the updated quantity and will confirm the revised quotation in this thread.")
    else:
        lines.append("To proceed, simply reply with your purchase order in this thread.")
    return "\n".join(lines)


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
