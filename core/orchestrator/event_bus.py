from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable, DefaultDict, Deque, Dict, List, Set

from schemas.events import SwarmEvent


logger = logging.getLogger("winged-tycoons.event-bus")
EventHandler = Callable[[SwarmEvent], Awaitable[None] | None]


class SwarmEventBus:
    """Small async event bus with bounded history and duplicate suppression."""

    def __init__(self, history_limit: int = 1000, handler_timeout_seconds: float = 10.0):
        if history_limit < 1:
            raise ValueError("history_limit must be positive")
        if handler_timeout_seconds <= 0:
            raise ValueError("handler_timeout_seconds must be positive")
        self._subscribers: DefaultDict[str, List[EventHandler]] = defaultdict(list)
        self._history: Deque[SwarmEvent] = deque(maxlen=history_limit)
        self._processed_keys: Set[str] = set()
        self._failed_handlers: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self.handler_timeout_seconds = handler_timeout_seconds

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        if not event_type.strip():
            raise ValueError("event_type cannot be blank")
        if handler not in self._subscribers[event_type]:
            self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        handlers = self._subscribers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    async def publish(self, event: SwarmEvent) -> bool:
        """Publish once per idempotency key and fan out handlers concurrently."""
        async with self._lock:
            if event.idempotency_key in self._processed_keys:
                return False
            self._processed_keys.add(event.idempotency_key)
            self._history.append(event)
            handlers = list(self._subscribers.get(event.event_type, []))

        if not handlers:
            return True

        results = await asyncio.gather(
            *(self._invoke(handler, event) for handler in handlers),
            return_exceptions=True,
        )
        for handler, result in zip(handlers, results):
            if isinstance(result, Exception):
                failure = {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "handler": getattr(handler, "__name__", repr(handler)),
                    "error": str(result),
                }
                self._failed_handlers.append(failure)
                logger.exception("Event handler failed: %s", failure)
        return True

    async def _invoke(self, handler: EventHandler, event: SwarmEvent) -> None:
        result = handler(event)
        if inspect.isawaitable(result):
            await asyncio.wait_for(result, timeout=self.handler_timeout_seconds)

    def get_history(self) -> List[SwarmEvent]:
        return list(self._history)

    def get_failed_handlers(self) -> List[Dict[str, Any]]:
        return list(self._failed_handlers)

    async def mark_processed(self, idempotency_key: str) -> None:
        async with self._lock:
            self._processed_keys.add(idempotency_key)

    def clear(self) -> None:
        self._history.clear()
        self._processed_keys.clear()
        self._failed_handlers.clear()
