"""Check PostgreSQL connectivity using the project's async SQLAlchemy driver."""

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.database_safety import resolve_database_url, validate_development_database_target


LOCAL_ENV_FILE = Path(__file__).resolve().parents[1] / ".env.local"


async def main() -> int:
    database_url = resolve_database_url(LOCAL_ENV_FILE)
    if not database_url:
        print("DATABASE_URL was not found in the process environment or .env.local.", file=sys.stderr)
        return 1
    try:
        validate_development_database_target(database_url, "development")
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            print(f"PostgreSQL connection OK (SELECT 1 = {result.scalar_one()}).")
        return 0
    except Exception as exc:
        print(f"PostgreSQL connection failed: {type(exc).__name__}.", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))