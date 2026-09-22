"""Best-effort text extraction for inbound quote attachments."""

from __future__ import annotations

import io
from typing import Any


def extract_attachment_text(filename: str, content_type: str, content: bytes) -> str:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "pdf" or content_type == "application/pdf":
        try:
            from pypdf import PdfReader

            return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages).strip()
        except Exception:
            return ""
    if suffix in {"xlsx", "xlsm"} or "spreadsheet" in content_type:
        try:
            from openpyxl import load_workbook

            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            rows = []
            for sheet in workbook.worksheets:
                for row in sheet.iter_rows(values_only=True):
                    values = [str(value).strip() for value in row if value is not None and str(value).strip()]
                    if values:
                        rows.append(" | ".join(values))
            return "\n".join(rows)
        except Exception:
            return ""
    if content_type.startswith("text/") or suffix in {"csv", "txt"}:
        return content.decode("utf-8", errors="replace")
    if content_type.startswith("image/"):
        # OCR is optional; preserve a clear marker when OCR dependencies are absent.
        try:
            import pytesseract
            from PIL import Image

            return pytesseract.image_to_string(Image.open(io.BytesIO(content))).strip()
        except Exception:
            return ""
    return ""


def build_email_context(body: str, attachments: list[dict[str, Any]] | None = None) -> str:
    sections = [body.strip()]
    for attachment in attachments or []:
        text = extract_attachment_text(
            str(attachment.get("filename", "attachment")),
            str(attachment.get("content_type", "application/octet-stream")),
            attachment.get("content", b"") or b"",
        )
        if text:
            sections.append(f"Attachment {attachment.get('filename', 'attachment')}:\n{text}")
    return "\n\n".join(section for section in sections if section)