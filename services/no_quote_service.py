"""No-quote rule: close RFQs we could not source and tell the customer in the same email thread."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("winged-tycoons-no-quote")

SWEEP_STATUSES = {"Supplier_Sourcing", "Sourcing_Failed"}
_AOG_PATTERN = re.compile(r"\bAOG\b|aircraft\s+on\s+ground", re.IGNORECASE)


def _hours(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def is_aog(rfq) -> bool:
    return bool(_AOG_PATTERN.search(getattr(rfq, "raw_text", "") or ""))


def deadline_for(rfq) -> datetime:
    created = rfq.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    hours = _hours("NO_QUOTE_AOG_HOURS", 4) if is_aog(rfq) else _hours("NO_QUOTE_HOURS", 48)
    return created + timedelta(hours=hours)


def _part_numbers(db, rfq) -> list[str]:
    parts = [
        (item.resolved_part_number or item.requested_part_number or "").strip()
        for item in db.get_rfq_items(rfq.id)
    ]
    parts = [p for p in parts if p]
    if not parts and rfq.part_number:
        parts = [p.strip() for p in rfq.part_number.split(",") if p.strip()]
    return parts


def _has_offers(db, parts: list[str]) -> bool:
    for part in parts:
        try:
            if db.get_supplier_offers_for_part(part):
                return True
        except Exception:
            logger.exception("Supplier offer lookup failed part=%s", part)
            return True  # never no-quote on uncertain data
    return False


def sweep_no_quote(now: datetime | None = None, db=None, comms=None) -> list[str]:
    """Mark overdue RFQs with no supplier offers as No_Quote and send the polite same-thread email."""
    if db is None:
        from services.db_service import db_service as db
    if comms is None:
        from services.communication_service import communication_service as comms
    now = now or datetime.now(timezone.utc)
    closed: list[str] = []
    for rfq in db.list_rfqs():
        if rfq.status not in SWEEP_STATUSES or getattr(rfq, "automation_paused", False):
            continue
        if now < deadline_for(rfq):
            continue
        parts = _part_numbers(db, rfq)
        if _has_offers(db, parts):
            continue
        try:
            db.update_rfq_status(rfq.id, "No_Quote")
        except Exception:
            logger.exception("No-quote transition failed rfq=%s", rfq.id)
            continue
        try:
            comms.send_rfq_no_quote(
                rfq_id=rfq.id,
                recipient=rfq.customer_email,
                customer_name=rfq.customer_name,
                part_numbers=parts,
                reply_to=rfq.thread_id,
            )
        except Exception:
            logger.exception("No-quote email failed rfq=%s", rfq.id)
        db.add_audit_log(
            rfq.id, "NoQuoteRule", "NO_QUOTE",
            "No supplier offers and no stock before the deadline; customer notified in the original thread.",
        )
        closed.append(rfq.id)
    return closed


def reopen_if_no_quote(db, rfq_id: str) -> bool:
    """A late supplier answer reopens a No_Quote RFQ for sourcing."""
    rfq = db.get_rfq(rfq_id)
    if not rfq or rfq.status != "No_Quote":
        return False
    db.update_rfq_status(rfq_id, "Supplier_Sourcing")
    db.add_audit_log(rfq_id, "NoQuoteRule", "REOPENED", "Late supplier offer received; RFQ reopened.")
    return True
