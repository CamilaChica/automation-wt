"""Seed the async PostgreSQL aviation parts tables.

Run after installing requirements and applying migrations:
    python scripts/seed_aviation_parts.py
"""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from services.async_database import create_engine_from_environment, session_scope, upsert_aviation_part


SEED_PARTS = [
    {"part_number": "060-1234-00", "description": "Main Landing Gear Actuator", "condition_code": "NE", "unit_price": Decimal("1250.00"), "lead_time_days": 3},
    {"part_number": "5-89356-42", "description": "Aircraft Window", "condition_code": "AR", "unit_price": Decimal("2400.00"), "lead_time_days": 5},
    {"part_number": "747-1011-00", "description": "Engine-Driven Hydraulic Pump", "condition_code": "OH", "unit_price": Decimal("1550.00"), "lead_time_days": 7},
]


async def main() -> None:
    engine = create_engine_from_environment()
    async with session_scope(engine) as session:
        for part in SEED_PARTS:
            await upsert_aviation_part(session, **part)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
