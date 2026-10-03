"""Safe inbound attachment validation and local quarantine storage."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import BinaryIO

from pydantic import BaseModel, Field


class AttachmentRecord(BaseModel):
    attachment_id: str
    filename: str
    content_type: str
    size_bytes: int = Field(..., ge=0)
    sha256: str
    stored_path: str | None = None
    status: str
    warning: str | None = None


class AttachmentService:
    allowed_extensions = {".pdf", ".png", ".jpg", ".jpeg", ".txt", ".csv", ".xlsx", ".xls", ".docx", ".doc"}
    document_extensions = {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg"}
    allowed_types = {
        "application/pdf", "image/png", "image/jpeg",
        "text/plain", "text/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    }
    max_bytes = 25 * 1024 * 1024

    def __init__(self, storage_dir: str | Path | None = None):
        self.storage_dir = Path(storage_dir or os.getenv("ATTACHMENT_STORAGE_DIR", "data/attachments"))
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def get_stored_path(self, attachment_id: str) -> Path | None:
        normalized_id = attachment_id.strip().upper()
        if not re.fullmatch(r"ATT-[0-9A-F]{16}", normalized_id):
            return None
        root = self.storage_dir.resolve()
        for extension in self.allowed_extensions:
            candidate = (self.storage_dir / f"{normalized_id}{extension}").resolve()
            if root in candidate.parents and candidate.is_file():
                return candidate
        return None

    def validate_and_store(self, filename: str, content_type: str, stream: BinaryIO) -> AttachmentRecord:
        content = stream.read(self.max_bytes + 1)
        digest = hashlib.sha256(content).hexdigest()
        attachment_id = f"ATT-{digest[:16].upper()}"
        if len(content) > self.max_bytes:
            return AttachmentRecord(attachment_id=attachment_id, filename=filename, content_type=content_type, size_bytes=len(content), sha256=digest, status="REJECTED", warning="Attachment exceeds 25MB limit.")
        suffix = Path(filename).suffix.lower()
        safe_name = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(filename).name)[:200] or f"upload{suffix}"
        detected_type = self._detect_type(suffix, content)
        if suffix not in self.allowed_extensions or detected_type is None:
            return AttachmentRecord(attachment_id=attachment_id, filename=safe_name, content_type=content_type, size_bytes=len(content), sha256=digest, status="REJECTED", warning="Unsupported or invalid file. Please upload a PDF, Word (.docx/.doc), CSV, Excel (.xlsx/.xls), JPG or PNG file.")
        target = self.storage_dir / f"{attachment_id}{suffix}"
        target.write_bytes(content)
        return AttachmentRecord(attachment_id=attachment_id, filename=safe_name, content_type=detected_type, size_bytes=len(content), sha256=digest, stored_path=str(target), status="ACCEPTED")

    @staticmethod
    def _detect_type(suffix: str, content: bytes) -> str | None:
        """Identify the file by its content, since browsers often mislabel CSV/Excel MIME types."""
        if not content:
            return None
        if suffix == ".pdf":
            return "application/pdf" if content.startswith(b"%PDF-") else None
        if suffix == ".png":
            return "image/png" if content.startswith(b"\x89PNG\r\n\x1a\n") else None
        if suffix in {".jpg", ".jpeg"}:
            return "image/jpeg" if content.startswith(b"\xff\xd8\xff") else None
        if suffix == ".xlsx":
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if content.startswith(b"PK\x03\x04") else None
        if suffix == ".xls":
            return "application/vnd.ms-excel" if content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1") else None
        if suffix == ".docx":
            # ZIP entry names are stored uncompressed, so a real Word file contains "word/".
            is_docx = content.startswith(b"PK\x03\x04") and b"word/" in content
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if is_docx else None
        if suffix == ".doc":
            return "application/msword" if content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1") else None
        if suffix in {".csv", ".txt"}:
            if b"\x00" in content[:8192]:
                return None
            for encoding in ("utf-8-sig", "cp1252", "latin-1"):
                try:
                    content.decode(encoding)
                    return "text/csv" if suffix == ".csv" else "text/plain"
                except UnicodeDecodeError:
                    continue
        return None
