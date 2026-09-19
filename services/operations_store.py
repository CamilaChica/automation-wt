"""SQLite persistence for RFQ, quote, inventory, and audit state."""

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict


DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "operations.db"


class OperationsStore:
    def __init__(self, path: str | Path | None = None):
        configured = path or os.getenv("OPERATIONS_DB_PATH")
        self.path = Path(configured) if configured else DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS operations_state (state_key TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            conn.commit()
        finally:
            conn.close()

    def load(self) -> Dict[str, Any] | None:
        conn = sqlite3.connect(self.path)
        try:
            row = conn.execute(
                "SELECT payload FROM operations_state WHERE state_key = 'current'"
            ).fetchone()
        finally:
            conn.close()
        return json.loads(row[0]) if row else None

    def save(self, state: Dict[str, Any]) -> None:
        payload = json.dumps(state, separators=(",", ":"))
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                "INSERT INTO operations_state (state_key, payload) VALUES ('current', ?) "
                "ON CONFLICT(state_key) DO UPDATE SET payload = excluded.payload",
                (payload,),
            )
            conn.commit()
        finally:
            conn.close()

    def clear(self) -> None:
        conn = sqlite3.connect(self.path)
        try:
            conn.execute("DELETE FROM operations_state WHERE state_key = 'current'")
            conn.commit()
        finally:
            conn.close()


operations_store = OperationsStore()
