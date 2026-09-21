from __future__ import annotations

import asyncio
from typing import Optional

from schemas.events import SwarmEvent


class HumanEscalationQueue:
    """In-memory HITL queue used locally and in deterministic tests."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[SwarmEvent] = asyncio.Queue()

    async def enqueue(self, event: SwarmEvent) -> None:
        await self._queue.put(event)

    async def dequeue(self, timeout: Optional[float] = None) -> SwarmEvent:
        if timeout is None:
            return await self._queue.get()
        return await asyncio.wait_for(self._queue.get(), timeout=timeout)

    def qsize(self) -> int:
        return self._queue.qsize()
