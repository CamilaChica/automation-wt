from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from models.async_models import Base
import models.operational_models  # noqa: F401 - register shared operational tables
from services.alembic_safety import is_read_only_alembic_command, validate_alembic_target
from services.database_safety import resolve_database_url

config = context.config
database_url = resolve_database_url(Path(__file__).resolve().parents[1] / ".env.local")
if not database_url:
    raise RuntimeError("Set DATABASE_URL in the process environment; Alembic does not load .env.")
if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


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
    command = getattr(getattr(config, "cmd_opts", None), "cmd", None)
    validate_alembic_target(command, database_url)
    connectable = async_engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    try:
        async with connectable.connect() as connection:
            async with connection.begin():
                if is_read_only_alembic_command(command) and connection.dialect.name == "postgresql":
                    await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                await connection.run_sync(
                    lambda sync_connection: context.configure(
                        connection=sync_connection,
                        target_metadata=target_metadata,
                        version_table_column_length=255,
                    )
                )
                await connection.run_sync(lambda _: context.run_migrations())
    finally:
        await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
