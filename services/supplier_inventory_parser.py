"""Deterministic row parsing for supplier inventory attachments."""

from __future__ import annotations

import csv
import io
import re
from typing import Any


ALIASES = {
    "part_number": {"part number", "part no", "part #", "pn", "p n", "p/n", "sku", "stock number", "item number", "material", "matnr", "part", "item"},
    "description": {"description", "part description", "item description", "desc", "nomenclature", "item desc", "part name"},
    "quantity_available": {"quantity", "qty", "available", "qty available", "quantity available", "stock", "on hand", "avail", "qty on hand", "stock qty", "qoh", "units"},
    "condition_code": {"condition", "cond", "condition code", "cd", "c/d", "state", "cond code"},
    "unit_price": {"price", "unit price", "cost", "unit cost", "price each", "unit_price", "unit_cost", "net price", "ea price", "list price", "each"},
    "currency": {"currency", "curr", "ccy"},
    "lead_time_days": {"lead time", "lead time days", "days", "lt", "delivery", "deliv", "lead-time", "lead"},
    "certificate_type": {"certificate", "certification", "cert", "trace", "8130", "easa", "tag", "cert type", "release", "doc", "docs", "tag type"},
    "availability_location": {"location", "warehouse", "ship from", "availability location", "loc", "whs", "city", "country", "site"},
}


def _cell_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _header_key(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9#]+", " ", _cell_text(value).lower())).strip()


def _split_pdf_line(line: str) -> list[str]:
    if "|" in line:
        return [cell.strip() for cell in line.split("|")]
    if "\t" in line:
        return [cell.strip() for cell in line.split("\t")]
    return [cell.strip() for cell in re.split(r"\s{2,}", line.strip())]


def _table_from_rows(rows: list[list[Any]], *, parser: str, sheet_name: str | None = None) -> dict[str, Any] | None:
    header_index = -1
    header_map: dict[str, int] = {}
    for index, row in enumerate(rows[:20]):
        mapped: dict[str, int] = {}
        for col_index, value in enumerate(row):
            key = _header_key(value)
            for field, aliases in ALIASES.items():
                if key in aliases:
                    mapped.setdefault(field, col_index)
                    break
        if "part_number" in mapped and len(mapped) >= 2:
            header_index = index
            header_map = mapped
            break
    if header_index < 0:
        return None

    headers = [_cell_text(value) for value in rows[header_index]]
    data_rows: list[dict[str, Any]] = []
    for offset, values in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any(_cell_text(value) for value in values):
            continue
        raw = {headers[index] or f"column_{index + 1}": value for index, value in enumerate(values) if index < len(headers)}
        normalized = {field: values[index] if index < len(values) else None for field, index in header_map.items()}
        normalized["raw_values"] = raw
        normalized["row_number"] = offset
        data_rows.append(normalized)
    return {"parser": parser, "sheet_name": sheet_name, "header_map": {key: headers[index] for key, index in header_map.items()}, "rows": data_rows}


def _workbook_rows(filename: str, content: bytes) -> list[dict[str, Any]]:
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix in {"xlsx", "xlsm"}:
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        return [
            table
            for sheet in workbook.worksheets
            if (table := _table_from_rows([list(row) for row in sheet.iter_rows(values_only=True)], parser="xlsx", sheet_name=sheet.title))
        ]
    if suffix == "xls":
        import xlrd

        workbook = xlrd.open_workbook(file_contents=content, on_demand=True)
        tables = []
        for sheet in workbook.sheets():
            table = _table_from_rows([sheet.row_values(index) for index in range(sheet.nrows)], parser="xls", sheet_name=sheet.name)
            if table:
                tables.append(table)
        return tables
    raise ValueError("Unsupported workbook format")


def _csv_rows(content: bytes) -> list[dict[str, Any]]:
    text = content.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [row for row in csv.reader(io.StringIO(text), dialect) if any(cell.strip() for cell in row)]
    table = _table_from_rows(rows, parser="csv")
    return [table] if table else []


def _pdf_rows(content: bytes) -> list[dict[str, Any]]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    tables = []
    for page_index, page in enumerate(reader.pages, start=1):
        text = page.extract_text(extraction_mode="layout") or ""
        rows = [_split_pdf_line(line) for line in text.splitlines() if line.strip()]
        table = _table_from_rows(rows, parser="pdf", sheet_name=f"page_{page_index}")
        if table:
            tables.append(table)
    return tables


def parse_supplier_inventory_attachment(filename: str, content_type: str, content: bytes) -> list[dict[str, Any]]:
    """Return normalized table blocks, or an empty list for unstructured files."""
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    try:
        if suffix in {"xlsx", "xlsm", "xls"}:
            return _workbook_rows(filename, content)
        if suffix == "csv" or content_type.lower() in {"text/csv", "application/csv"}:
            return _csv_rows(content)
        if suffix == "pdf" or content_type.lower() == "application/pdf":
            return _pdf_rows(content)
    except Exception:
        return []
    return []


def normalize_inventory_row(row: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Normalize a source row and return a rejection reason when required data is invalid."""
    normalized = dict(row)
    part_number = re.sub(r"\s*[-]\s*", "-", _cell_text(row.get("part_number"))).replace(" ", "").upper()
    normalized["part_number"] = part_number or None
    normalized["description"] = _cell_text(row.get("description")) or None
    normalized["condition_code"] = _cell_text(row.get("condition_code")).upper() or None
    normalized["certificate_type"] = _cell_text(row.get("certificate_type")) or None
    normalized["availability_location"] = _cell_text(row.get("availability_location")) or None
    currency = _cell_text(row.get("currency")).upper()
    price_text = _cell_text(row.get("unit_price"))
    if not currency:
        match = re.search(r"\b(USD|EUR|GBP|CAD|AUD)\b", price_text.upper())
        currency = match.group(1) if match else "USD"
    normalized["currency"] = currency
    try:
        normalized["unit_price"] = float(re.sub(r"[^0-9.\-]", "", price_text)) if price_text else None
    except ValueError:
        return normalized, "unit_price is not numeric"
    for field in ("quantity_available", "lead_time_days"):
        value = _cell_text(row.get(field))
        match = re.search(r"\d+", value)
        normalized[field] = int(match.group()) if match else None
    if not part_number:
        return normalized, "part_number is missing"
    if normalized["quantity_available"] is None:
        return normalized, "quantity_available is missing or invalid"
    return normalized, None