"""Formal 8.5x11 quotation document rendering and PDF generation."""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = BASE_DIR / "WT-RFQ-Template" / "winged-tycoons-quotation-template.html"
EMAIL_TEMPLATE_PATH = BASE_DIR / "WT-RFQ-Template" / "winged-tycoons-quotation-email.html"

FL_TAX_RATE = Decimal("0.07")  # 7% Miami-Dade Florida sales tax


def _pattern(name: str) -> re.Pattern:
    return re.compile(
        r'(<(?P<tag>td|span|strong|h1|p)\b[^>]*\bdata-field="' + re.escape(name) + r'"[^>]*>)'
        r"(?P<body>.*?)(</(?P=tag)>)",
        re.S,
    )


def _set_field(text: str, name: str, value: Any) -> str:
    pat = _pattern(name)
    if not pat.search(text):
        return text
    safe_val = html.escape(str(value if value is not None else ""), quote=False)
    return pat.sub(lambda m: m.group(1) + safe_val + m.group(4), text, count=1)


def _num(value: Any) -> Decimal:
    try:
        cleaned = re.sub(r"[^0-9.\-]", "", str(value if value is not None else ""))
        return Decimal(cleaned or "0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _money(value: Decimal) -> str:
    return f"{value:,.2f}"


def _row_html(row_idx: int) -> str:
    f = lambda col: f'data-field="item_{row_idx}_{col}" contenteditable'
    return (
        f'<tr><td {f("pn")}></td><td {f("desc")}></td>'
        f'<td class="c" {f("cond")}></td><td {f("cert")}></td><td {f("trace")}></td>'
        f'<td {f("lead")}></td><td {f("warranty")}></td><td class="c" {f("qty")}></td>'
        f'<td {f("unit")} style="text-align:right"></td><td {f("total")}></td></tr>\n'
    )


def render_quotation_html(
    *,
    quote_number: str,
    quote_date: str | None = None,
    valid_until: str | None = None,
    rfq_reference: str | None = None,
    payment_terms: str = "100% prepayment",
    incoterms: str = "EXW – unit location confirmed by supplier",
    currency: str = "USD",
    customer_company: str = "",
    customer_contact: str = "",
    customer_email: str = "",
    customer_phone: str = "",
    customer_address: str = "",
    customer_tax_id: str = "",
    items: List[Dict[str, Any]] | None = None,
    notes: str = "Unit ships same day upon PO and payment receipt.",
    tax: Decimal | float | None = None,
    other: Decimal | float | None = None,
    authorized_company: str = "Winged Tycoons",
    authorized_name: str = "Camila Chica",
    signature_date: str | None = None,
) -> str:
    """Render quotation data into the formal 8.5x11 HTML quotation document."""
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Quotation template not found at {TEMPLATE_PATH}")

    content = TEMPLATE_PATH.read_text(encoding="utf-8")
    items = items or []

    today_str = quote_date or datetime.now(timezone.utc).strftime("%d %b, %Y")
    sig_date_str = signature_date or today_str

    # Header and Customer / Quote Metadata
    content = _set_field(content, "quote_number", quote_number)
    content = _set_field(content, "customer_company", customer_company)
    content = _set_field(content, "customer_contact", customer_contact)
    content = _set_field(content, "customer_email", customer_email)
    content = _set_field(content, "customer_phone", customer_phone)
    content = _set_field(content, "customer_address", customer_address)
    content = _set_field(content, "customer_tax_id", customer_tax_id)

    content = _set_field(content, "quote_date", today_str)
    content = _set_field(content, "valid_until", valid_until or "Subject to prior sale")
    content = _set_field(content, "rfq_reference", rfq_reference or quote_number)
    content = _set_field(content, "currency", currency)
    content = _set_field(content, "currency_label", currency)
    content = _set_field(content, "payment_terms", payment_terms)
    content = _set_field(content, "incoterms", incoterms)
    content = _set_field(content, "notes", notes)
    content = _set_field(content, "authorized_company", authorized_company)
    content = _set_field(content, "authorized_name", authorized_name)
    content = _set_field(content, "signature_date", sig_date_str)

    # Adjust item table rows
    num_items = len(items)
    # Ensure table has enough rows
    existing_rows = len(re.findall(r'data-field="item_\d+_pn"', content))
    if num_items > existing_rows:
        extra_rows = "".join(_row_html(r) for r in range(existing_rows + 1, num_items + 1))
        content = content.replace("</tbody>", extra_rows + "</tbody>", 1)

    subtotal = Decimal("0")
    # Populate provided item rows
    for idx, item in enumerate(items, start=1):
        pn = str(item.get("part_number") or item.get("pn") or "")
        desc = str(item.get("description") or item.get("desc") or pn)
        cond = str(item.get("condition") or item.get("cond") or "NE")
        cert = str(item.get("certificate_type") or item.get("cert") or "FAA 8130-3")
        trace = str(item.get("trace") or "OEM / 121 Trace")
        lead = str(item.get("lead_time") or item.get("lead_time_days") or "Stock - same day")
        if isinstance(lead, (int, float)):
            lead = f"{int(lead)} days" if lead > 0 else "Stock - same day"
        warranty = str(item.get("warranty") or item.get("warranty_terms") or "30 Days")
        qty = _num(item.get("quantity") or item.get("qty") or 1)
        unit = _num(item.get("unit_price") or item.get("unit_cost") or item.get("unit") or 0)
        line_total = qty * unit
        subtotal += line_total

        qty_str = str(int(qty)) if qty == qty.to_integral_value() else str(qty)

        content = _set_field(content, f"item_{idx}_pn", pn)
        content = _set_field(content, f"item_{idx}_desc", desc)
        content = _set_field(content, f"item_{idx}_cond", cond)
        content = _set_field(content, f"item_{idx}_cert", cert)
        content = _set_field(content, f"item_{idx}_trace", trace)
        content = _set_field(content, f"item_{idx}_lead", lead)
        content = _set_field(content, f"item_{idx}_warranty", warranty)
        content = _set_field(content, f"item_{idx}_qty", qty_str)
        content = _set_field(content, f"item_{idx}_unit", _money(unit))
        content = _set_field(content, f"item_{idx}_total", _money(line_total))

    # Clear any unused default placeholder rows beyond num_items
    total_table_rows = len(re.findall(r'data-field="item_\d+_pn"', content))
    for empty_idx in range(num_items + 1, total_table_rows + 1):
        for col in ("pn", "desc", "cond", "cert", "trace", "lead", "warranty", "qty", "unit", "total"):
            content = _set_field(content, f"item_{empty_idx}_{col}", "")

    # Calculate Totals
    tax_val = _num(tax) if tax is not None else Decimal("0.00")
    other_val = _num(other) if other is not None else Decimal("0.00")
    grand_total = subtotal + tax_val + other_val

    content = _set_field(content, "subtotal", _money(subtotal))
    content = _set_field(content, "tax", _money(tax_val))
    content = _set_field(content, "other", _money(other_val))
    content = _set_field(content, "total", _money(grand_total))

    return content


async def render_quotation_pdf_async(html_content: str) -> bytes:
    """Render HTML string to PDF bytes asynchronously using Playwright chromium."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
        try:
            page = await browser.new_page()
            await page.set_content(html_content, wait_until="networkidle")
            pdf_bytes = await page.pdf(
                format="Letter",
                print_background=True,
                margin={"top": "0in", "bottom": "0in", "left": "0in", "right": "0in"},
            )
            return pdf_bytes
        finally:
            await browser.close()


def render_quotation_pdf(html_content: str) -> bytes:
    """Synchronous entrypoint for PDF rendering."""
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, render_quotation_pdf_async(html_content)).result()
        return asyncio.run(render_quotation_pdf_async(html_content))
    except Exception as exc:
        logger.warning("PDF generation failed error=%s", exc)
        return b""
