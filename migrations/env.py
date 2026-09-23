from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from alembic import context
from sqlalchemy import inspect, pool, text
from sqlalchemy.ext.asyncio import async_engine_from_config

from models.async_models import Base
import models.operational_models  # noqa: F401 - register shared operational tables

config = context.config
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
if os.getenv("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1))
target_metadata = Base.metadata


def _widen_existing_version_table(connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    if inspect(connection).has_table("alembic_version"):
        connection.execute(text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)"))


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_column_length=255,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(_widen_existing_version_table)
        await connection.commit()
        await connection.run_sync(
            lambda sync_connection: context.configure(
                connection=sync_connection,
                target_metadata=target_metadata,
                version_table_column_length=255,
            )
        )
        async with connection.begin():
            await connection.run_sync(lambda _: context.run_migrations())
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
