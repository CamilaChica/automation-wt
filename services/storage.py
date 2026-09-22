"""Async attachment storage with S3 production storage and local development fallback."""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from pathlib import Path
from urllib.parse import quote


class AttachmentStorage:
    def __init__(self, storage_dir: str | Path | None = None):
        self.storage_dir = Path(storage_dir or os.getenv("ATTACHMENT_STORAGE_DIR", "data/attachments"))
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.bucket_name = os.getenv("AWS_S3_BUCKET_NAME", "").strip()
        self.region_name = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")).strip()

    @property
    def use_s3(self) -> bool:
        return bool(self.bucket_name)

    @staticmethod
    def _safe_filename(filename: str) -> str:
        name = Path(filename).name
        return re.sub(r"[^A-Za-z0-9._-]", "_", name) or "attachment.bin"

    def _local_path(self, file_key: str) -> Path:
        candidate = (self.storage_dir / file_key).resolve()
        root = self.storage_dir.resolve()
        if root not in candidate.parents:
            raise ValueError("Attachment key escapes local storage directory.")
        return candidate

    def _client(self):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 is required when AWS_S3_BUCKET_NAME is configured.") from exc
        return boto3.client("s3", region_name=self.region_name)

    async def upload_rfq_attachment(self, file_bytes: bytes, filename: str, content_type: str) -> str:
        file_key = f"rfq/{uuid.uuid4().hex}-{self._safe_filename(filename)}"
        if self.use_s3:
            client = self._client()
            await asyncio.to_thread(
                client.put_object,
                Bucket=self.bucket_name,
                Key=file_key,
                Body=file_bytes,
                ContentType=content_type,
            )
            return file_key

        local_path = self._local_path(file_key)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(local_path.write_bytes, file_bytes)
        return file_key

    async def get_presigned_download_url(self, file_key: str) -> str:
        if self.use_s3:
            client = self._client()
            return await asyncio.to_thread(
                client.generate_presigned_url,
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": file_key},
                ExpiresIn=int(os.getenv("ATTACHMENT_URL_TTL_SECONDS", "900")),
            )

        path = self._local_path(file_key)
        if not path.is_file():
            raise FileNotFoundError(file_key)
        return path.as_uri()


storage_service = AttachmentStorage()
