"""Dedicated loop for transactional outbound email delivery."""

from __future__ import annotations

import logging
import os
import time
import asyncio

from services.communication_service import communication_service
from services.operations_store import operations_store
from services.async_database import preflight_database

logger = logging.getLogger("winged-tycoons-outbox-dispatcher")


def run() -> None:
    interval = max(1, int(os.getenv("OUTBOX_POLL_INTERVAL_SECONDS", "5")))
    if operations_store.storage_engine == "postgresql":
        asyncio.run(preflight_database())
    while True:
        try:
            if operations_store.storage_engine != "postgresql":
                logger.warning("Transactional outbox requires PostgreSQL; retrying after interval")
            else:
                result = communication_service.dispatch_outbox_once(limit=int(os.getenv("OUTBOX_BATCH_SIZE", "25")))
                if result["sent"] or result["failed"]:
                    logger.info("Outbox batch sent=%d failed=%d", result["sent"], result["failed"])
        except Exception:
            logger.exception("Outbox dispatch cycle failed")
        time.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    run()