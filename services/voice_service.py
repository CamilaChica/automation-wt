import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable


_human_queue: list[dict[str, Any]] = []
_queue_lock = threading.Lock()


def _normalized_part_number(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _inventory_payload(item: Any) -> dict[str, Any]:
    return {
        "part_number": str(getattr(item, "part_number", "")),
        "description": str(getattr(item, "description", "") or ""),
        "quantity": int(getattr(item, "quantity_available", 0) or 0),
        "condition_code": str(getattr(item, "condition_code", "")),
        "certificate_type": str(getattr(item, "certificate_type", "") or ""),
        "has_full_trace": bool(getattr(item, "has_full_trace", False)),
    }


def check_inventory_availability(part_number: str, inventory: Iterable[Any] = ()) -> dict[str, Any]:
    query = _normalized_part_number(part_number.strip())
    if not query:
        return {"matches": [], "message": "Enter a part number to search inventory."}

    matches = [
        _inventory_payload(item)
        for item in inventory
        if query in _normalized_part_number(_inventory_payload(item)["part_number"])
        or _normalized_part_number(_inventory_payload(item)["part_number"]) in query
    ]
    return {
        "matches": matches,
        "message": f"Found {len(matches)} inventory match(es)." if matches else "No matching inventory was found.",
    }


def _normalize_reference(value: str) -> str:
    """Treat 'RFQ 681941', 'rfq681941', '681941' and 'RFQ-681941' as the same reference."""
    import re

    text = (value or "").strip().upper()
    match = re.fullmatch(r"(?:([A-Z]{2,4})[\s_#:-]*)?(\d[\d\s-]*)", text)
    if not match:
        return text
    prefix = match.group(1) or "RFQ"
    digits = re.sub(r"\D", "", match.group(2))
    return f"{prefix}-{digits}"


def get_order_status(rfq_or_order_id: str, rfqs: Iterable[Any] = ()) -> dict[str, Any]:
    query = _normalize_reference(rfq_or_order_id)
    for rfq in rfqs:
        if _normalize_reference(str(getattr(rfq, "id", ""))) != query:
            continue
        status = str(getattr(rfq, "status", "In review"))
        return {
            "found": True,
            "id": getattr(rfq, "id", query),
            "customer_name": getattr(rfq, "customer_name", "Customer"),
            "part_number": getattr(rfq, "part_number", None),
            "status": status,
            "tracking_details": None,
            "review_notice": "Operator review is required." if "review" in status.lower() or "hold" in status.lower() else None,
        }

    return {"found": False, "id": query, "message": "No matching RFQ or order was found."}


def get_customer_order_status(
    rfq_or_order_id: str,
    customer_email: str,
    rfqs: Iterable[Any] = (),
) -> dict[str, Any]:
    query = _normalize_reference(rfq_or_order_id)
    email = customer_email.strip().lower()
    for rfq in rfqs:
        if (
            _normalize_reference(str(getattr(rfq, "id", ""))) != query
            or str(getattr(rfq, "customer_email", "")).lower() != email
        ):
            continue
        status = str(getattr(rfq, "status", "In review"))
        return {
            "found": True,
            "id": getattr(rfq, "id", query),
            "part_number": getattr(rfq, "part_number", None),
            "status": status,
            "tracking_details": None,
            "review_notice": "Your request is under operator review." if "review" in status.lower() or "hold" in status.lower() else None,
        }
    return {"found": False, "id": query, "message": "No matching request was found for your account."}


def log_customer_concern(
    issue_type: str,
    details: str,
    part_number: str,
    customer_email: str = "",
) -> dict[str, Any]:
    normalized_type = issue_type.strip().lower()
    normalized_details = details.strip()
    review_terms = re.compile(
        r"\b(ambiguous|unclear|itar|ear|export.control|controlled item|military end.use|foreign destination|"
        r"eur|euro|euros|gbp|pounds?|cad|canadian dollars?|aud|australian dollars?|jpy|yen|non.usd)\b",
        re.IGNORECASE,
    )
    requires_review = normalized_type in {"other", "ambiguous", "export_control", "non_usd"}
    requires_review = requires_review or bool(review_terms.search(normalized_details))

    entry = {
        "id": f"VC-{uuid.uuid4().hex[:8].upper()}",
        "issue_type": normalized_type or "unspecified",
        "details": normalized_details,
        "part_number": part_number.strip().upper(),
        "customer_email": customer_email.strip().lower(),
        "status": "Escalated to operator" if requires_review else "Logged",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _queue_lock:
        _human_queue.insert(0, entry)
        del _human_queue[100:]
    return {"logged": True, "requires_review": requires_review, "concern": entry}


def get_voice_dashboard(rfqs: Iterable[Any] = (), inventory: Iterable[Any] = ()) -> dict[str, Any]:
    requests = [{
        "id": str(getattr(rfq, "id", "")),
        "customer_name": str(getattr(rfq, "customer_name", "") or ""),
        "part_number": str(getattr(rfq, "part_number", "") or ""),
        "status": str(getattr(rfq, "status", "") or ""),
        "tracking_details": None,
        "review_notice": "Operator review is required." if any(term in str(getattr(rfq, "status", "")).lower() for term in ("review", "hold")) else None,
    } for rfq in rfqs if getattr(rfq, "id", None)]
    with _queue_lock:
        queue = [entry.copy() for entry in _human_queue]
    return {"inventory": [_inventory_payload(item) for item in inventory], "requests": requests[:10], "human_queue": queue}