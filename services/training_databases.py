"""Dedicated access layer for client and supplier communication agent training databases."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

ROOT = Path(__file__).resolve().parent.parent
CLIENT_TRAINING_DB_PATH = ROOT / "data" / "client_communications_training.db"
SUPPLIER_TRAINING_DB_PATH = ROOT / "data" / "supplier_communications_training.db"


class TrainingDatabaseService:
    """Manages dedicated model training databases for Client and Supplier communication agents."""

    def __init__(
        self,
        client_db_path: Path | str = CLIENT_TRAINING_DB_PATH,
        supplier_db_path: Path | str = SUPPLIER_TRAINING_DB_PATH,
    ):
        self.client_db_path = Path(client_db_path)
        self.supplier_db_path = Path(supplier_db_path)

    def _get_connection(self, db_type: Literal["client", "supplier"]) -> sqlite3.Connection:
        path = self.client_db_path if db_type == "client" else self.supplier_db_path
        if not path.exists():
            from scripts.build_training_databases import build_both_training_databases
            build_both_training_databases()
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_database_summary(self, db_type: Literal["client", "supplier"]) -> Dict[str, Any]:
        """Return high-level summary and metadata for the requested training database."""
        conn = self._get_connection(db_type)
        cur = conn.cursor()
        
        cur.execute("SELECT key, value FROM database_metadata")
        meta = {row["key"]: row["value"] for row in cur.fetchall()}

        table_prefix = "client" if db_type == "client" else "supplier"
        cur.execute(f"SELECT count(*) FROM {table_prefix}_training_samples")
        sample_count = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM model_instruction_tuning")
        instruction_count = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM few_shot_demonstrations")
        demo_count = cur.fetchone()[0]

        cur.execute(f"SELECT DISTINCT scenario FROM {table_prefix}_training_samples")
        scenarios = [row[0] for row in cur.fetchall()]

        conn.close()
        return {
            "database_type": db_type,
            "database_path": str(self.client_db_path if db_type == "client" else self.supplier_db_path),
            "metadata": meta,
            "sample_count": sample_count,
            "instruction_tuning_count": instruction_count,
            "few_shot_demonstration_count": demo_count,
            "scenarios": scenarios,
        }

    def list_training_samples(
        self,
        db_type: Literal["client", "supplier"],
        limit: int = 50,
        offset: int = 0,
        scenario: Optional[str] = None,
        direction: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List samples from client or supplier training database with filtering."""
        conn = self._get_connection(db_type)
        cur = conn.cursor()
        table = "client_training_samples" if db_type == "client" else "supplier_training_samples"

        query = f"SELECT * FROM {table} WHERE 1=1"
        params: List[Any] = []
        if scenario:
            query += " AND scenario = ?"
            params.append(scenario)
        if direction:
            query += " AND direction = ?"
            params.append(direction)
        query += " ORDER BY id LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cur.execute(query, params)
        rows = [dict(row) for row in cur.fetchall()]
        for r in rows:
            for json_field in ("expected_extracted_data", "expected_actions"):
                if r.get(json_field) and isinstance(r[json_field], str):
                    try:
                        r[json_field] = json.loads(r[json_field])
                    except Exception:
                        pass
        conn.close()
        return rows

    def get_instruction_tuning_dataset(
        self,
        db_type: Literal["client", "supplier"],
        task_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Fetch standard (system, user, assistant) fine-tuning pairs."""
        conn = self._get_connection(db_type)
        cur = conn.cursor()
        query = "SELECT * FROM model_instruction_tuning WHERE 1=1"
        params: List[Any] = []
        if task_type:
            query += " AND task_type = ?"
            params.append(task_type)
        query += " ORDER BY id LIMIT ?"
        params.append(limit)

        cur.execute(query, params)
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return rows

    def export_openai_jsonl(
        self,
        db_type: Literal["client", "supplier"],
        target_path: Path | str,
    ) -> int:
        """Export instruction tuning data in standard OpenAI fine-tuning JSONL format."""
        dataset = self.get_instruction_tuning_dataset(db_type, limit=1000)
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with open(target, "w", encoding="utf-8") as f:
            for row in dataset:
                item = {
                    "messages": [
                        {"role": "system", "content": row["system_prompt"]},
                        {"role": "user", "content": row["user_prompt"]},
                        {"role": "assistant", "content": row["assistant_response"]},
                    ]
                }
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
                count += 1
        return count


training_db_service = TrainingDatabaseService()
