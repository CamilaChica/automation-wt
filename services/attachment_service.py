"""Safe inbound attachment validation and local quarantine storage."""

from __future__ import annotations

import hashlib
import os
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
    allowed_types = {
        "application/pdf", "image/png", "image/jpeg",
        "text/plain", "text/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    max_bytes = 25 * 1024 * 1024

    def __init__(self, storage_dir: str | Path | None = None):
        self.storage_dir = Path(storage_dir or os.getenv("ATTACHMENT_STORAGE_DIR", "data/attachments"))
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def validate_and_store(self, filename: str, content_type: str, stream: BinaryIO) -> AttachmentRecord:
        content = stream.read(self.max_bytes + 1)
        digest = hashlib.sha256(content).hexdigest()
        attachment_id = f"ATT-{digest[:16].upper()}"
        if len(content) > self.max_bytes:
            return AttachmentRecord(attachment_id=attachment_id, filename=filename, content_type=content_type, size_bytes=len(content), sha256=digest, status="REJECTED", warning="Attachment exceeds 25MB limit.")
        if content_type not in self.allowed_types or Path(filename).suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg", ".txt", ".csv", ".xlsx"}:
            return AttachmentRecord(attachment_id=attachment_id, filename=filename, content_type=content_type, size_bytes=len(content), sha256=digest, status="REJECTED", warning="Unsupported attachment type.")
        target = self.storage_dir / f"{attachment_id}{Path(filename).suffix.lower()}"
        target.write_bytes(content)
        return AttachmentRecord(attachment_id=attachment_id, filename=filename, content_type=content_type, size_bytes=len(content), sha256=digest, stored_path=str(target), status="ACCEPTED")
