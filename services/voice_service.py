import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable


VOICE_INVENTORY = [
    {
        "part_number": "060-1234-00",
        "description": "Main Wheel Assembly",
        "quantity": 4,
        "condition_code": "FN",
        "condition_description": "Factory New",
        "unit_price": 4250.00,
        "lead_time": "Immediate",
    },
    {
        "part_number": "45-0912-3",
        "description": "Hydraulic Pump",
        "quantity": 0,
        "condition_code": "OH",
        "condition_description": "Overhauled",
        "unit_price": 1800.00,
        "lead_time": "14 Days",
    },
    {
        "part_number": "060-5678-01",
        "description": "Brake Rotor Disk",
        "quantity": 12,
        "condition_code": "NE",
        "condition_description": "New Surplus",
        "unit_price": 850.00,
        "lead_time": "Immediate",
    },
    {
        "part_number": "10-60539-1",
        "description": "Starter Generator",
        "quantity": 2,
        "condition_code": "AR",
        "condition_description": "As Removed",
        "unit_price": 2100.00,
        "lead_time": "3 Days",
    },
]

VOICE_REQUESTS = [
    {
        "id": "WT-48291",
        "customer_name": "AeroNorth Maintenance",
        "part_number": "060-5678-01",
        "status": "Pending Quote",
        "tracking_details": None,
        "review_notice": None,
    },
    {
        "id": "WT-48276",
        "customer_name": "Pacific Flight Group",
        "part_number": "10-60539-1",
        "status": "Inventory Reserved",
        "tracking_details": "Shipment preparation in progress",
        "review_notice": None,
    },
    {
        "id": "WT-48240",
        "customer_name": "Meridian Aero Services",
        "part_number": "45-0912-3",
        "status": "Escalated to Sales",
        "tracking_details": None,
        "review_notice": "Sales review required before quote release",
    },
]

_human_queue: list[dict[str, Any]] = []
_queue_lock = threading.Lock()


def _normalized_part_number(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def check_inventory_availability(part_number: str) -> dict[str, Any]:
    query = _normalized_part_number(part_number.strip())
    if not query:
        return {"matches": [], "message": "Enter a part number to search inventory."}

    matches = [
        item.copy()
        for item in VOICE_INVENTORY
        if query in _normalized_part_number(item["part_number"])
        or _normalized_part_number(item["part_number"]) in query
    ]
    return {
        "matches": matches,
        "message": f"Found {len(matches)} inventory match(es)." if matches else "No matching inventory was found.",
    }


def get_order_status(rfq_or_order_id: str, rfqs: Iterable[Any] = ()) -> dict[str, Any]:
    query = rfq_or_order_id.strip().upper()
    for request in VOICE_REQUESTS:
        if request["id"].upper() == query:
            return {"found": True, **request}

    for rfq in rfqs:
        if str(getattr(rfq, "id", "")).upper() != query:
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
    query = rfq_or_order_id.strip().upper()
    email = customer_email.strip().lower()
    for rfq in rfqs:
        if (
            str(getattr(rfq, "id", "")).upper() != query
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


def get_voice_dashboard(rfqs: Iterable[Any] = ()) -> dict[str, Any]:
    requests = [request.copy() for request in VOICE_REQUESTS]
    known_ids = {request["id"] for request in requests}
    for rfq in rfqs:
        rfq_id = str(getattr(rfq, "id", ""))
        if not rfq_id or rfq_id in known_ids:
            continue
        requests.append({
            "id": rfq_id,
            "customer_name": getattr(rfq, "customer_name", "Customer"),
            "part_number": getattr(rfq, "part_number", "-"),
            "status": getattr(rfq, "status", "Pending Quote"),
            "tracking_details": None,
            "review_notice": None,
        })
    with _queue_lock:
        queue = [entry.copy() for entry in _human_queue]
    return {"inventory": [item.copy() for item in VOICE_INVENTORY], "requests": requests[:10], "human_queue": queue}