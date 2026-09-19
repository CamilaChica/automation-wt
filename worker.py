"""Long-running shared mailbox poller for the MVP deployment."""

import logging
import os
import re
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from services.mailbox_service import fetch_inbox_messages
from services.supplier_email_loader import SupplierEmailLoader
from services.communication_service import communication_service
from services.supplier_database import supplier_db
from scripts.backup_sqlite import main as backup_sqlite

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("winged-tycoons-mailbox-worker")


def _missing_supplier_fields(email_text: str, result: dict) -> list[str]:
    """Identify fields that cannot be safely inferred from a supplier reply."""
    missing = []
    if not re.search(r"\$\s*[0-9]|(?:price|cost)\s*[:=]?\s*[0-9]", email_text, re.IGNORECASE):
        missing.append("unit price and currency")
    if not re.search(r"(?:qty|quantity|available|in stock|each|pcs?)\b", email_text, re.IGNORECASE):
        missing.append("quantity available")
    if not re.search(r"(?:FAA\s*(?:Form\s*)?8130[-\s]?3|EASA\s*Form\s*1|certificate|release tag|CoC)", email_text, re.IGNORECASE):
        missing.append("release certificate and trace documentation")
    if not re.search(r"(?:lead\s*time|ship\s*in|delivery|ready to ship|days?)", email_text, re.IGNORECASE):
        missing.append("lead time or estimated ship date")
    if not re.search(r"(?:valid until|valid for|expires|expiration)", email_text, re.IGNORECASE):
        missing.append("quote validity or expiration date")
    return missing


def run() -> None:
    interval = int(os.getenv("MAILBOX_POLL_INTERVAL_SECONDS", "60"))
    backup_interval = int(os.getenv("SQLITE_BACKUP_INTERVAL_SECONDS", "86400"))
    last_backup_at = 0.0
    loader = SupplierEmailLoader()
    while True:
        now = time.time()
        if now - last_backup_at >= backup_interval:
            try:
                backup_sqlite()
                last_backup_at = now
                logger.info("SQLite backup completed at %s", datetime.now(timezone.utc).isoformat())
            except Exception:
                logger.exception("SQLite backup failed")

        for task in supplier_db.list_due_communication_tasks():
            try:
                result = communication_service.process_due_task(task)
                supplier_db.mark_communication_task_sent(task["id"])
                logger.info("Sent scheduled %s communication to %s -> %s", task["task_type"], task["recipient"], result["transmission_status"])
            except Exception:
                supplier_db.mark_communication_task_failed(task["id"])
                logger.exception("Scheduled communication failed for task %s", task["id"])

        for mailbox in ("sales", "purchasing"):
            try:
                messages = fetch_inbox_messages(mailbox)
                logger.info("Mailbox %s: read %d message bodies", mailbox, len(messages))
                for message in messages:
                    body = (message.get("body") or "").strip()
                    if not body:
                        continue
                    email_text = (
                        f"From: {message.get('from', '')}\n"
                        f"Subject: {message.get('subject', '')}\n\n"
                        f"{body}"
                    )
                    if mailbox != "purchasing":
                        logger.info(
                            "Mailbox %s message %s retained for customer communication; supplier ingestion skipped",
                            mailbox,
                            message.get("message_id"),
                        )
                        continue
                    result = loader.load_raw_email_text(email_text)
                    logger.info("Mailbox %s processed message %s -> %s", mailbox, message.get("message_id"), result)
                    if result.get("success") and mailbox == "purchasing":
                        sender = message.get("from", "")
                        if result.get("unit_cost", 0) and "@" in sender:
                            discount_task = communication_service.schedule_supplier_discount_request(
                                recipient=sender,
                                supplier_name=result["supplier_name"],
                                part_number=result["part_number"],
                                unit_cost=float(result["unit_cost"]),
                                source_email_id=result["source_email_id"],
                                reply_to=message.get("message_id"),
                            )
                            logger.info("Scheduled supplier discount request -> %s", discount_task)
                        missing_fields = _missing_supplier_fields(email_text, result)
                        if missing_fields and "@" in sender:
                            clarification = communication_service.request_missing_supplier_fields(
                                recipient=sender,
                                part_number=result["part_number"],
                                missing_fields=missing_fields,
                                reply_to=message.get("message_id"),
                            )
                            logger.info(
                                "Requested missing supplier fields for %s in thread %s -> %s",
                                result["part_number"],
                                message.get("message_id"),
                                clarification,
                            )
            except Exception:
                logger.exception("Mailbox poll failed for %s", mailbox)
        time.sleep(interval)


if __name__ == "__main__":
    run()
