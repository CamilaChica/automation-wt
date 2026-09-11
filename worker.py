"""Long-running shared mailbox poller for the MVP deployment."""

import logging
import os
import time

from services.mailbox_service import fetch_inbox_headers

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("winged-tycoons-mailbox-worker")


def run() -> None:
    interval = int(os.getenv("MAILBOX_POLL_INTERVAL_SECONDS", "60"))
    while True:
        for mailbox in ("sales", "purchasing"):
            try:
                messages = fetch_inbox_headers(mailbox)
                logger.info("Mailbox %s: read %d message headers", mailbox, len(messages))
            except Exception:
                logger.exception("Mailbox poll failed for %s", mailbox)
        time.sleep(interval)


if __name__ == "__main__":
    run()
