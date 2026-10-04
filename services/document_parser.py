"""Best-effort text extraction for inbound quote attachments."""

from __future__ import annotations

import io
import logging
from functools import lru_cache
from threading import Lock
from typing import Any
from zipfile import ZipFile
from xml.etree import ElementTree

logger = logging.getLogger(__name__)
_OCR_LOCK = Lock()


@lru_cache(maxsize=1)
def _ocr_engine():
    from rapidocr import RapidOCR

    return RapidOCR(params={
        "EngineConfig.onnxruntime.intra_op_num_threads": 1,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "Det.limit_type": "max",
        "Det.limit_side_len": 960,
        "Cls.cls_batch_num": 1,
        "Rec.rec_batch_num": 1,
    })


def _ocr_image(image) -> str:
    import numpy as np

    if image.width * image.height > 20_000_000:
        raise ValueError("OCR image exceeds the 20-megapixel limit.")
    with _OCR_LOCK:
        result = _ocr_engine()(np.array(image.convert("RGB")))
    if any(float(score) < 0.85 for score in result.scores or []):
        raise ValueError("OCR text confidence is below 0.85; manual document review is required.")
    return "\n".join(result.txts or [])


def extract_attachment_text(filename: str, content_type: str, content: bytes) -> str:
    if not content or len(content) > 25 * 1024 * 1024:
        logger.warning("document_extraction_rejected filename=%s reason=empty_or_oversized", filename)
        return ""
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "pdf" or content_type == "application/pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            if len(reader.pages) > 30:
                raise ValueError("PDF exceeds the 30-page extraction limit.")
            texts = [page.extract_text() or "" for page in reader.pages]
            missing = [index for index, text in enumerate(texts) if not text.strip()]
            if missing:
                import pypdfium2

                document = pypdfium2.PdfDocument(content)
                try:
                    for index in missing:
                        page = document[index]
                        bitmap = None
                        try:
                            width, height = page.get_size()
                            scale = min(2.0, (20_000_000 / (width * height)) ** 0.5)
                            bitmap = page.render(scale=scale)
                            texts[index] = _ocr_image(bitmap.to_pil())
                            if not texts[index].strip():
                                raise ValueError("PDF page has no readable text after OCR.")
                        finally:
                            if bitmap is not None:
                                bitmap.close()
                            page.close()
                finally:
                    document.close()
            return "\n".join(texts).strip()
        except Exception as exc:
            logger.warning("document_extraction_failed filename=%s error=%s", filename, type(exc).__name__)
            return ""
    if suffix == "docx":
        try:
            with ZipFile(io.BytesIO(content)) as archive:
                entry = archive.getinfo("word/document.xml")
                if entry.file_size > 10 * 1024 * 1024:
                    raise ValueError("Word document text exceeds extraction limit.")
                root = ElementTree.fromstring(archive.read(entry))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            return "\n".join(
                "".join(paragraph.itertext())
                for paragraph in root.findall(".//w:p", ns)
            ).strip()
        except Exception as exc:
            logger.warning("document_extraction_failed filename=%s error=%s", filename, type(exc).__name__)
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
        except Exception as exc:
            logger.warning("document_extraction_failed filename=%s error=%s", filename, type(exc).__name__)
            return ""
    if suffix == "xls":
        try:
            import xlrd

            workbook = xlrd.open_workbook(file_contents=content, on_demand=True)
            rows = []
            for sheet in workbook.sheets():
                for row_index in range(sheet.nrows):
                    values = [str(value).strip() for value in sheet.row_values(row_index) if str(value).strip()]
                    if values:
                        rows.append(" | ".join(values))
            return "\n".join(rows)
        except Exception as exc:
            logger.warning("document_extraction_failed filename=%s error=%s", filename, type(exc).__name__)
            return ""
    if content_type.startswith("text/") or suffix in {"csv", "txt"}:
        return content.decode("utf-8", errors="replace")
    if content_type.startswith("image/"):
        try:
            from PIL import Image

            with Image.open(io.BytesIO(content)) as image:
                return _ocr_image(image).strip()
        except Exception as exc:
            logger.warning("document_extraction_failed filename=%s error=%s", filename, type(exc).__name__)
            return ""
    logger.warning("document_extraction_unsupported filename=%s type=%s", filename, content_type)
    return ""


def build_email_context(body: str, attachments: list[dict[str, Any]] | None = None) -> str:
    sections = [str(body or "")]
    for attachment in attachments or []:
        text = extract_attachment_text(
            str(attachment.get("filename", "attachment")),
            str(attachment.get("content_type", "application/octet-stream")),
            attachment.get("content", b"") or b"",
        )
        if text:
            sections.append(f"Attachment {attachment.get('filename', 'attachment')}:\n{text}")
        else:
            sections.append(
                f"Attachment {attachment.get('filename', 'attachment')}: "
                "[UNREADABLE DOCUMENT: no facts extracted; do not infer its contents or certification.]"
            )
    return "\n\n".join(section for section in sections if section.strip())