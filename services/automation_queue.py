"""Durable, idempotent async execution boundary for automation work."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from services.operations_store import operations_store

Handler = Callable[[], Any | Awaitable[Any]]


class AutomationQueue:
    def __init__(self):
        self._handlers: dict[str, Handler] = {}

    def register(self, event_type: str, handler: Handler) -> None:
        self._handlers[event_type] = handler

    async def enqueue(
        self,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
        idempotency_key: str,
        max_attempts: int = 3,
    ) -> str:
        event_id = operations_store.record_automation_event(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            status="QUEUED",
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
        )
        existing = self._event(event_id)
        if existing and existing["status"] == "SUCCEEDED":
            return event_id
        await self.run(event_id, max_attempts=max_attempts)
        return event_id

    async def run(self, event_id: str, *, max_attempts: int = 3) -> None:
        event = self._event(event_id)
        if not event:
            raise ValueError(f"Automation event '{event_id}' was not found.")
        handler = self._handlers.get(event["event_type"])
        if not handler:
            operations_store.update_automation_event(event_id, status="FAILED", attempts=event["attempts"], error="No handler registered.")
            raise ValueError(f"No handler registered for '{event['event_type']}'.")
        attempts = int(event["attempts"])
        while attempts < max_attempts:
            attempts += 1
            operations_store.update_automation_event(event_id, status="RUNNING", attempts=attempts)
            try:
                result = handler()
                if asyncio.iscoroutine(result):
                    result = await result
                operations_store.update_automation_event(event_id, status="SUCCEEDED", attempts=attempts, result=json.dumps(result, default=str))
                return
            except Exception as exc:
                if attempts >= max_attempts:
                    operations_store.update_automation_event(event_id, status="FAILED", attempts=attempts, error=str(exc))
                    raise
                await asyncio.sleep(0)

    def _event(self, event_id: str):
        import sqlite3

        conn = sqlite3.connect(operations_store.path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM automation_events WHERE id = ?", (event_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


automation_queue = AutomationQueue()