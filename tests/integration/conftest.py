"""Integration-test options for optional external-provider verification."""

import os
import re
import uuid

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from models.async_models import Base
import models.operational_models  # noqa: F401 - register operational tables


@pytest.fixture
async def disposable_postgres_engine():
    if "TEST_DATABASE_URL" in os.environ and not os.environ["TEST_DATABASE_URL"].strip():
        pytest.skip("TEST_DATABASE_URL is explicitly disabled in this process.")
    database_url = os.getenv("TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL persistence integration tests.")

    url = make_url(database_url)
    database_name = (url.database or "").lower()
    host = (url.host or "").lower()
    if not re.search(r"(^|[_-])(test|disposable)([_-]|$)", database_name):
        pytest.fail("TEST_DATABASE_URL must target a database named with a test/disposable marker.")
    if host not in {"localhost", "127.0.0.1", "::1"} and os.getenv("POSTGRES_TEST_ALLOW_REMOTE") != "true":
        pytest.fail("Remote TEST_DATABASE_URL requires POSTGRES_TEST_ALLOW_REMOTE=true.")

    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+asyncpg")
    if url.drivername != "postgresql+asyncpg":
        pytest.fail("TEST_DATABASE_URL must use the asyncpg PostgreSQL driver.")

    schema_name = f"test_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(url, pool_pre_ping=True)
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
        test_engine = create_async_engine(
            url,
            pool_pre_ping=True,
            connect_args={"server_settings": {"search_path": schema_name}},
        )
        try:
            async with test_engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            yield test_engine
        finally:
            await test_engine.dispose()
            async with admin_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
    finally:
        await admin_engine.dispose()


def pytest_addoption(parser):
    parser.addoption(
        "--run-live-llm",
        action="store_true",
        default=False,
        help="Run opt-in live OpenAI/Anthropic/Gemini verification tests.",
    )


def pytest_configure(config):
    if config.getoption("--run-live-llm"):
        os.environ["RUN_LIVE_LLM"] = "1"
