"""Dedicated worker for durable RFQ resume events."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from services.operations_store import operations_store

logger = logging.getLogger("winged-tycoons-rfq-resume-worker")


def dispatch_once(limit: int = 10) -> dict[str, int]:
    events = []
    for event_type in ("process_new_rfq", "resume_waiting_rfq"):
        remaining = max(0, limit - len(events))
        if remaining == 0:
            break
        events.extend(operations_store.claim_automation_events(event_type=event_type, limit=remaining))
    succeeded = failed = 0
    if not events:
        return {"succeeded": succeeded, "failed": failed}
    from services.orchestration_service import orchestration_service

    for event in events:
        try:
            result = asyncio.run(orchestration_service.process_rfq_pipeline(event["entity_id"]))
            operations_store.update_automation_event(
                event["id"], status="SUCCEEDED", attempts=int(event["attempts"]), result=json.dumps(result, default=str),
            )
            succeeded += 1
        except Exception as exc:
            status = "QUEUED" if int(event["attempts"]) < int(event["max_attempts"]) else "FAILED"
            operations_store.update_automation_event(
                event["id"], status=status, attempts=int(event["attempts"]),
                result=event.get("result"), error=f"{type(exc).__name__}: {exc}",
            )
            logger.exception("RFQ resume failed event=%s rfq=%s", event["id"], event["entity_id"])
            failed += 1
    return {"succeeded": succeeded, "failed": failed}


def run() -> None:
    interval = max(1, int(os.getenv("RFQ_RESUME_POLL_INTERVAL_SECONDS", "15")))
    sweep_interval = max(60, int(os.getenv("NO_QUOTE_SWEEP_INTERVAL_SECONDS", "300")))
    last_sweep = 0.0
    while True:
        try:
            result = dispatch_once()
            if result["succeeded"] or result["failed"]:
                logger.info("RFQ resume batch succeeded=%d failed=%d", result["succeeded"], result["failed"])
        except Exception:
            logger.exception("RFQ resume queue poll failed")
        if time.monotonic() - last_sweep >= sweep_interval:
            last_sweep = time.monotonic()
            try:
                from services.no_quote_service import sweep_no_quote

                closed = sweep_no_quote()
                if closed:
                    logger.info("No-quote rule closed rfqs=%s", ",".join(closed))
            except Exception:
                logger.exception("No-quote sweep failed")
        time.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    run()