"""Long-running shared mailbox poller for the MVP deployment."""

import logging
import os
import time

from services.integration_db_service import integration_db_service
from services.mailbox_service import fetch_inbox_headers, fetch_inbox_messages
from services.purchasing_email_parser import parse_purchasing_email

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("winged-tycoons-mailbox-worker")


def run() -> None:
    interval = int(os.getenv("MAILBOX_POLL_INTERVAL_SECONDS", "60"))
    while True:
        for mailbox in ("sales", "purchasing"):
            try:
                messages = fetch_inbox_headers(mailbox)
                logger.info("Mailbox %s: read %d message headers", mailbox, len(messages))
                if mailbox == "purchasing":
                    for full_message in fetch_inbox_messages("purchasing", limit=10):
                        try:
                            parsed = parse_purchasing_email(
                                f"{full_message['subject']}\n{full_message['body']}",
                                source=f"imap:{full_message['message_id']}",
                            )
                            integration_db_service.upsert_supplier_inventory_email(parsed)
                            logger.info(
                                "Processed purchasing email %s for part %s",
                                full_message["message_id"],
                                parsed["part_number"],
                            )
                        except Exception:
                            logger.exception(
                                "Failed to parse/store purchasing email %s",
                                full_message.get("message_id", "unknown"),
                            )
            except Exception:
                logger.exception("Mailbox poll failed for %s", mailbox)
        time.sleep(interval)


if __name__ == "__main__":
    run()
