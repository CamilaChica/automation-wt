import hashlib
import re
from typing import Any, Dict

_SUPPLIER_RE = re.compile(r"supplier\s*:\s*(.+)", re.IGNORECASE)
_EMAIL_RE = re.compile(r"email\s*:\s*([^\s,;]+@[^\s,;]+)", re.IGNORECASE)
_CONTACT_RE = re.compile(r"contact\s*:\s*(.+)", re.IGNORECASE)
_PART_RE = re.compile(r"(?:part|p\/n|pn)\s*:\s*([A-Z0-9\-]+)", re.IGNORECASE)
_QTY_RE = re.compile(r"(?:qty|quantity)\s*:\s*(\d+)", re.IGNORECASE)
_PRICE_RE = re.compile(r"(?:unit\s*cost|price)\s*:\s*\$?([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_COND_RE = re.compile(r"(?:condition)\s*:\s*([A-Z]+)", re.IGNORECASE)
_CERT_RE = re.compile(r"(?:cert|certificate)\s*:\s*(.+)", re.IGNORECASE)
_TRACE_RE = re.compile(r"(full\s*trace|traceable|8130|easa)", re.IGNORECASE)
_SN_RE = re.compile(r"(?:serial|sn)\s*:\s*([A-Z0-9\-]+)", re.IGNORECASE)


def _match(pattern: re.Pattern[str], text: str, default: str = "") -> str:
    found = pattern.search(text)
    return found.group(1).strip() if found else default


def parse_purchasing_email(raw_email: str, source: str = "purchasing_email") -> Dict[str, Any]:
    if not raw_email.strip():
        raise ValueError("raw_email cannot be empty")

    supplier_name = _match(_SUPPLIER_RE, raw_email, "Unknown Supplier")
    contact_email = _match(_EMAIL_RE, raw_email, "unknown@supplier.invalid")
    contact_name = _match(_CONTACT_RE, raw_email, supplier_name)
    part_number = _match(_PART_RE, raw_email).upper()
    if not part_number:
        raise ValueError("Unable to parse part number from purchasing email")

    quantity_text = _match(_QTY_RE, raw_email, "0")
    quantity = max(0, int(quantity_text))
    if quantity <= 0:
        raise ValueError("Unable to parse a positive quantity from purchasing email")

    unit_cost_text = _match(_PRICE_RE, raw_email, "0")
    unit_cost = float(unit_cost_text)
    if unit_cost <= 0:
        raise ValueError("Unable to parse a positive unit cost from purchasing email")

    condition_code = _match(_COND_RE, raw_email, "NE").upper()
    certificate_type = _match(_CERT_RE, raw_email, "FAA 8130-3")
    serial_number = _match(_SN_RE, raw_email)
    has_full_trace = bool(_TRACE_RE.search(raw_email))
    supplier_slug = re.sub(r"[^a-z0-9]+", "-", supplier_name.lower()).strip("-")
    supplier_id = f"SUP-{hashlib.sha1(supplier_slug.encode('utf-8')).hexdigest()[:8].upper()}"
    inventory_id = f"INV-{hashlib.sha1((supplier_id + part_number + serial_number).encode('utf-8')).hexdigest()[:10].upper()}"

    return {
        "source": source,
        "supplier_id": supplier_id,
        "supplier_name": supplier_name,
        "contact_name": contact_name,
        "contact_email": contact_email,
        "part_number": part_number,
        "quantity": quantity,
        "unit_cost": unit_cost,
        "condition_code": condition_code,
        "certificate_type": certificate_type,
        "serial_number": serial_number or None,
        "has_full_trace": has_full_trace,
        "inventory_id": inventory_id,
        "warehouse_location": "Supplier Feed",
    }
