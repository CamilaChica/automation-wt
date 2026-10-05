"""Conservative classifier for inbound customer mailbox messages."""

from __future__ import annotations

import re
from typing import Any


_PO_NUMBER = re.compile(
    r"\b(?:purchase\s+order|p\.?o\.?)\s+(?:number|no\.?)\s*[:#]?\s*([A-Z0-9][A-Z0-9/_-]{2,})\b|"
    r"\b(?:purchase\s+order|p\.?o\.?)\s*#\s*([A-Z0-9][A-Z0-9/_-]{2,})\b|"
    r"\bPO[-_]([A-Z0-9][A-Z0-9/_-]{2,})\b",
    re.IGNORECASE,
)
_PO_MENTION = re.compile(r"\b(?:purchase\s+order|\bPO\s*(?:#|number|no\.?))\b", re.IGNORECASE)
_PART_REQUEST = re.compile(r"\b(?:part\s*(?:number|no\.?|#)|P/?N|PN)\s*[:#=\t|,]", re.IGNORECASE)
_EXPLICIT_RFQ = re.compile(
    r"\b(?:RFQ|request\s+(?:for\s+)?(?:a\s+)?(?:quote|quotation|pricing)|please\s+quote|"
    r"requesting\s+(?:a\s+)?quote|(?:best|your)\s+(?:quote|price|pricing)|price\s+and\s+availability|"
    r"pricing\s+and\s+availability|quote\s+(?:me|us|for))\b",
    re.IGNORECASE,
)


def classify_inbound_customer_message(message: dict[str, Any], *, has_related_quote: bool) -> dict[str, str | None]:
    subject = str(message.get("subject") or "")
    body = str(message.get("body") or "")
    attachments = " ".join(str(item.get("filename") or "") for item in message.get("attachments") or [])
    source = f"{subject}\n{body}\n{attachments}"
    po_match = _PO_NUMBER.search(source)
    if po_match or (has_related_quote and _PO_MENTION.search(source)):
        po_number = next((value for value in po_match.groups() if value), None) if po_match else None
        return {"category": "purchase_order", "po_number": po_number}
    if has_related_quote and (
        "?" in body
        or re.search(r"\b(?:can|could|would|what|when|where|how|please confirm|please advise|please send|please provide|please share|please attach|need more information)\b", body, re.I)
    ):
        return {"category": "client_question", "po_number": None}
    explicit_rfq = _EXPLICIT_RFQ.search(source)
    if explicit_rfq or (_PART_REQUEST.search(source) and re.search(r"\b(?:qty|quantity|need|require|quote)\b", source, re.I)):
        return {"category": "rfq", "po_number": None}
    return {"category": "other", "po_number": None}