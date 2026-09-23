"""Continuous supplier-mail inventory ingestion worker.

The worker is intentionally separate from the API process. It performs bounded
polls, uses message-id idempotency, parses attachment text, and optionally
mirrors normalized records into PostgreSQL when DATABASE_URL is configured.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Callable

from services.async_database import create_engine_from_environment, session_scope, upsert_aviation_part, upsert_supplier_quote
from services.document_parser import build_email_context
from services.mailbox_service import fetch_inbox_messages
from services.supplier_database import supplier_db
from services.supplier_email_loader import SupplierEmailLoader
from services.communication_service import communication_service

logger = logging.getLogger("winged-tycoons-inventory-ingestion")


class InventoryIngestionWorker:
    def __init__(
        self,
        *,
        fetch_messages: Callable[..., list[dict[str, Any]]] = fetch_inbox_messages,
        loader: SupplierEmailLoader | None = None,
    ):
        self.fetch_messages = fetch_messages
        self.loader = loader or SupplierEmailLoader()
        self.mailbox = os.getenv("INVENTORY_INGESTION_MAILBOX", "purchasing")
        self.poll_interval_seconds = int(os.getenv("INVENTORY_INGESTION_POLL_INTERVAL_SECONDS", "60"))
        explicit_postgres = os.getenv("INVENTORY_INGESTION_POSTGRES_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.postgres_enabled = bool(os.getenv("DATABASE_URL", "").strip()) and explicit_postgres

    @staticmethod
    def _email_text(message: dict[str, Any]) -> str:
        header = (
            f"From: {message.get('from', '')}\n"
            f"Subject: {message.get('subject', '')}\n\n"
            f"{message.get('body', '')}"
        )
        return build_email_context(header, message.get("attachments"))

    async def _persist_postgres(self, result: dict[str, Any], message: dict[str, Any]) -> None:
        if not self.postgres_enabled or not result.get("success"):
            return
        engine = create_engine_from_environment()
        try:
            async with session_scope(engine) as session:
                part = await upsert_aviation_part(
                    session,
                    part_number=str(result["part_number"]),
                    description=str(result.get("description") or "Supplier-provided aviation part"),
                    condition_code=result.get("condition_code") or "NE",
                    unit_price=result.get("unit_cost"),
                    currency="USD",
                    warranty_terms=result.get("warranty_terms"),
                    lead_time_days=int(result.get("lead_time_days") or 0),
                )
                await upsert_supplier_quote(
                    session,
                    supplier_email=str(result.get("supplier_email") or message.get("from") or "unknown@example.com"),
                    part_id=part.id,
                    quoted_price=result.get("unit_cost"),
                    raw_email_id=result.get("source_email_id"),
                    has_trace_docs=bool(result.get("trace_documents") or result.get("certificate_type")),
                    quantity_available=result.get("quantity_available"),
                    condition_code=result.get("condition_code"),
                    certificate_type=result.get("certificate_type"),
                    lead_time_days=result.get("lead_time_days"),
                    availability_location=result.get("availability_location"),
                    warranty_terms=result.get("warranty_terms"),
                    trace_documents=json.dumps(result.get("trace_documents") or []),
                )
        finally:
            await engine.dispose()

    def process_message(self, message: dict[str, Any]) -> dict[str, Any]:
        message_id = str(message.get("message_id") or "").strip()
        if message_id and supplier_db.is_email_processed(self.mailbox, message_id):
            return {"success": True, "skipped": True, "message_id": message_id}
        body = str(message.get("body") or "").strip()
        if not body and not message.get("attachments"):
            return {"success": False, "skipped": True, "error": "Message has no body or attachments."}

        result = self.loader.load_raw_email_text(
            self._email_text(message),
            mailbox=self.mailbox,
            message_id=message_id or None,
            attachments=message.get("attachments") or [],
        )
        mirror_warning = None
        if result.get("success"):
            try:
                for item in result.get("items") or [result]:
                    item_result = {**result, **item}
                    asyncio.run(self._persist_postgres(item_result, message))
            except Exception as exc:
                mirror_warning = f"PostgreSQL mirror pending: {type(exc).__name__}"
                logger.exception("Supplier inventory mirror failed for %s", message_id or "unknown")
            sender = str(message.get("from") or "")
            if "@" in sender and result.get("unit_cost"):
                communication_service.schedule_supplier_discount_request(
                    recipient=sender,
                    supplier_name=str(result.get("supplier_name") or "Supplier Team"),
                    part_number=str(result["part_number"]),
                    unit_cost=float(result["unit_cost"]),
                    source_email_id=str(result.get("source_email_id") or message_id),
                    reply_to=message_id or None,
                    quantity=int(result.get("quantity_available") or 1),
                )
        response = {"message_id": message_id, "result": result, "success": bool(result.get("success"))}
        if mirror_warning:
            response["persistence_warning"] = mirror_warning
        return response

    def poll_once(self, limit: int = 25) -> list[dict[str, Any]]:
        messages = self.fetch_messages(self.mailbox, limit=limit)
        results = []
        for message in messages:
            try:
                results.append(self.process_message(message))
            except Exception as exc:
                logger.exception("Inventory message processing failed: %s", message.get("message_id", "unknown"))
                results.append({"message_id": message.get("message_id", ""), "success": False, "error": str(exc)})
        return results

    def run_forever(self) -> None:
        while True:
            started = time.monotonic()
            self.poll_once()
            elapsed = time.monotonic() - started
            time.sleep(max(0, self.poll_interval_seconds - elapsed))


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    InventoryIngestionWorker().run_forever()
