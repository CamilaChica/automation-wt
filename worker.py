"""Long-running shared mailbox poller for the MVP deployment."""

import logging
import os
import time

from services.mailbox_service import fetch_inbox_headers
from services.mailbox_service import fetch_inbox_messages
from services.purchasing_email_parser import ingest_supplier_quote_messages
from services.relational_db import ensure_schema

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("winged-tycoons-mailbox-worker")


def run() -> None:
    interval = int(os.getenv("MAILBOX_POLL_INTERVAL_SECONDS", "60"))
    ensure_schema()
    while True:
        for mailbox in ("sales", "purchasing"):
            try:
                messages = fetch_inbox_headers(mailbox)
                logger.info("Mailbox %s: read %d message headers", mailbox, len(messages))
                if mailbox == "purchasing":
                    quote_messages = fetch_inbox_messages(mailbox, limit=10)
                    ingested = ingest_supplier_quote_messages(quote_messages)
                    logger.info("Mailbox %s: ingested %d supplier quote messages", mailbox, len(ingested))
            except Exception:
                logger.exception("Mailbox poll failed for %s", mailbox)
        time.sleep(interval)


if __name__ == "__main__":
    run()
