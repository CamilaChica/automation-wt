"""LLM tools to fill and edit the Winged Tycoons quotation template.

Every editable value in the HTML template carries a data-field="..." name.
The tools below read the template (or the working copy if one exists),
change those fields, and save the result to OUTPUT_PATH.
"""
from __future__ import annotations

import html
import re
import shutil
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Optional

try:
    from langchain_core.tools import tool
except ImportError:  # module still works (as plain functions) without langchain
    def tool(func=None, *_a, **_k):
        return func if func else (lambda f: f)

BASE = Path(__file__).resolve().parent
TEMPLATE_PATH = BASE / "winged-tycoons-quotation-template.html"  # never modified
OUTPUT_PATH = BASE / "quotation-output.html"                      # working copy
MAX_ROWS = 20
FL_TAX_RATE = Decimal("0.07")  # Miami-Dade: 6% state + 1% county


# ---------- helpers ----------
def _load() -> str:
    src = OUTPUT_PATH if OUTPUT_PATH.exists() else TEMPLATE_PATH
    return src.read_text(encoding="utf-8")


def _save(text: str) -> None:
    OUTPUT_PATH.write_text(text, encoding="utf-8")


def _pattern(name: str) -> re.Pattern:
    return re.compile(
        r'(<(?P<tag>td|span|strong)\b[^>]*\bdata-field="' + re.escape(name) + r'"[^>]*>)'
        r"(?P<body>.*?)(</(?P=tag)>)",
        re.S,
    )


def _get(text: str, name: str) -> Optional[str]:
    m = _pattern(name).search(text)
    if not m:
        return None
    return html.unescape(re.sub(r"<[^>]+>", "", m.group("body"))).strip()


def _set(text: str, name: str, value) -> str:
    pat = _pattern(name)
    if not pat.search(text):
        raise KeyError(name)
    safe = html.escape(str(value), quote=False)
    return pat.sub(lambda m: m.group(1) + safe + m.group(4), text, count=1)


def _num(value) -> Decimal:
    try:
        return Decimal(re.sub(r"[^0-9.\-]", "", str(value)) or "0")
    except InvalidOperation:
        return Decimal("0")


def _money(value: Decimal) -> str:
    return f"{value:,.2f}"


def _row_count(text: str) -> int:
    return len(re.findall(r'data-field="item_\d+_pn"', text))


def _row_html(n: int) -> str:
    f = lambda c: f'data-field="item_{n}_{c}" contenteditable'
    return (
        f'<tr><td {f("pn")}></td><td {f("desc")}></td>'
        f'<td class="c" {f("cond")}></td><td {f("cert")}></td><td {f("trace")}></td>'
        f'<td {f("lead")}></td><td {f("warranty")}></td><td class="c" {f("qty")}></td>'
        f'<td {f("unit")} style="text-align:right"></td><td {f("total")}></td></tr>\n'
    )


def _recalc(text: str, tax=None, other=None) -> str:
    subtotal = sum(
        (_num(_get(text, f"item_{r}_total")) for r in range(1, _row_count(text) + 1)),
        Decimal("0"),
    )
    tax_v = _num(tax) if tax is not None else (subtotal * FL_TAX_RATE).quantize(Decimal("0.01"))
    other_v = _num(other) if other is not None else _num(_get(text, "other"))
    text = _set(text, "subtotal", _money(subtotal))
    text = _set(text, "tax", _money(tax_v))
    text = _set(text, "other", _money(other_v))
    return _set(text, "total", _money(subtotal + tax_v + other_v))


# ---------- tools ----------
@tool
def list_quote_fields() -> Dict[str, str]:
    """Return every editable field of the quotation (name -> current value).

    Call this first to see the valid field names, e.g. quote_number,
    quote_date, valid_until, rfq_reference, payment_terms, incoterms,
    currency, currency_label, customer_company, customer_contact,
    customer_email, customer_phone, customer_address, customer_tax_id,
    notes, subtotal, tax, other, total, authorized_company, authorized_name,
    signature_date, and per line item item_<row>_pn / _desc / _cond / _cert /
    _trace / _lead / _warranty / _qty / _unit / _total.
    """
    text = _load()
    names = re.findall(r'data-field="([^"]+)"', text)
    return {n: _get(text, n) or "" for n in names}


@tool
def update_quote_fields(fields: Dict[str, str]) -> str:
    """Set one or more quotation fields at once.

    Args:
        fields: mapping of field name to new text, for example
            {"customer_company": "Aerotechnic", "quote_date": "05 Oct, 2026",
             "valid_until": "04 Nov, 2026", "authorized_name": "Camila Chica"}.
    Setting "currency" also updates the currency shown in the total label.
    Use set_line_item for part rows (it also recalculates totals).
    Returns a summary of what changed and any unknown field names.
    """
    text = _load()
    done, unknown = [], []
    fields = dict(fields)
    if "currency" in fields and "currency_label" not in fields:
        fields["currency_label"] = fields["currency"]
    for name, value in fields.items():
        try:
            text = _set(text, name, value)
            done.append(name)
        except KeyError:
            unknown.append(name)
    _save(text)
    msg = f"Updated: {', '.join(done) or 'nothing'}."
    if unknown:
        msg += f" Unknown fields (use list_quote_fields): {', '.join(unknown)}."
    return msg


@tool
def set_line_item(
    row: int,
    part_number: str,
    description: str,
    condition: str,
    quantity: float,
    unit_price: float,
    cert: str = "",
    trace: str = "",
    lead_time: str = "",
    warranty: str = "",
) -> str:
    """Fill one row of the items table and recalculate subtotal and total.

    Args:
        row: 1-based row number. The template has 4 rows; a higher number
            (up to 20) adds rows automatically, in order.
        part_number: P/N, e.g. "C20534100".
        description: e.g. "BRAKE ASSY".
        condition: condition code, e.g. "OH".
        quantity: number of units.
        unit_price: price per unit in the quote currency.
        cert: tag / certificate, e.g. "FAA 8130-3", "Dual Release", "CoC".
        trace: traceability, e.g. "121 Trace", "OEM Trace", "Birth Trace".
        lead_time: e.g. "Stock - same day", "5 days".
        warranty: e.g. "90 Days".
    The row total is quantity x unit_price.
    """
    if row < 1 or row > MAX_ROWS:
        return f"Row must be between 1 and {MAX_ROWS}."
    text = _load()
    while _row_count(text) < row:
        text = text.replace("</tbody>", _row_html(_row_count(text) + 1) + "</tbody>", 1)
    qty, unit = _num(quantity), _num(unit_price)
    qty_txt = str(int(qty)) if qty == qty.to_integral_value() else str(qty)
    for col, val in (
        ("pn", part_number),
        ("desc", description),
        ("cond", condition),
        ("cert", cert),
        ("trace", trace),
        ("lead", lead_time),
        ("warranty", warranty),
        ("qty", qty_txt),
        ("unit", _money(unit)),
        ("total", _money(qty * unit)),
    ):
        text = _set(text, f"item_{row}_{col}", val)
    text = _recalc(text)
    _save(text)
    return f"Row {row} set. Total: {_get(text, 'total')}."


@tool
def recalculate_totals(tax: Optional[float] = None, other: Optional[float] = None) -> str:
    """Recompute subtotal and quote total from the line items.

    Args:
        tax: optional tax amount. If omitted, 7% Florida tax is applied to the
            subtotal. Pass 0 when the client provides a Florida Resale
            Certificate (DR-13) or the unit ships outside Florida.
        other: optional 'Other' charge to set (keeps the current value if omitted).
    """
    text = _recalc(_load(), tax, other)
    _save(text)
    return (
        f"Subtotal {_get(text, 'subtotal')}, tax {_get(text, 'tax')}, "
        f"other {_get(text, 'other')}, total {_get(text, 'total')}."
    )


@tool
def reset_quote() -> str:
    """Discard all edits and start again from the blank template."""
    shutil.copyfile(TEMPLATE_PATH, OUTPUT_PATH)
    return f"Reset. Working copy: {OUTPUT_PATH}"


QUOTE_TOOLS = [list_quote_fields, update_quote_fields, set_line_item, recalculate_totals, reset_quote]
