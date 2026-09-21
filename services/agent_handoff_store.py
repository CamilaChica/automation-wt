"""Durable agent-to-agent handoff payloads."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field


class AgentHandoff(BaseModel):
    handoff_id: str
    rfq_id: str
    from_agent: str
    to_agent: str
    payload: dict
    created_at: str


class AgentHandoffStore:
    def __init__(self, path: str | Path = "data/operations.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS agent_handoffs (handoff_id TEXT PRIMARY KEY, rfq_id TEXT NOT NULL, from_agent TEXT NOT NULL, to_agent TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)")

    def save(self, rfq_id: str, from_agent: str, to_agent: str, payload: dict) -> AgentHandoff:
        handoff = AgentHandoff(handoff_id=f"HND-{uuid.uuid4().hex[:12].upper()}", rfq_id=rfq_id, from_agent=from_agent, to_agent=to_agent, payload=payload, created_at=datetime.now(timezone.utc).isoformat())
        with sqlite3.connect(self.path) as connection:
            connection.execute("INSERT INTO agent_handoffs VALUES (?, ?, ?, ?, ?, ?)", (handoff.handoff_id, handoff.rfq_id, handoff.from_agent, handoff.to_agent, json.dumps(handoff.payload), handoff.created_at))
        return handoff

    def list_for_rfq(self, rfq_id: str) -> list[AgentHandoff]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute("SELECT handoff_id, rfq_id, from_agent, to_agent, payload, created_at FROM agent_handoffs WHERE rfq_id = ? ORDER BY created_at", (rfq_id,)).fetchall()
        return [AgentHandoff(handoff_id=row[0], rfq_id=row[1], from_agent=row[2], to_agent=row[3], payload=json.loads(row[4]), created_at=row[5]) for row in rows]
