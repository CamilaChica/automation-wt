from __future__ import annotations

import re
import os
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url


LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
DISPOSABLE_DATABASE_NAME = re.compile(r"(^|[_-])(test|testing|dev|local|disposable)([_-]|$)", re.IGNORECASE)


def resolve_database_url(local_env_file: Path) -> str:
    for name in ("DATABASE_URL", "TEST_DATABASE_URL", "ASYNC_DATABASE_URL"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    local_values = dotenv_values(local_env_file)
    return str(local_values.get("DATABASE_URL") or local_values.get("TEST_DATABASE_URL") or "").strip()


def validate_development_database_target(database_url: str, environment: str) -> None:
    if environment.strip().lower() not in {"dev", "development", "test", "testing"} or not database_url:
        return
    url = make_url(database_url)
    host = (url.host or "").lower()
    database = (url.database or "").lower()
    if host not in LOCAL_DATABASE_HOSTS or not DISPOSABLE_DATABASE_NAME.search(database):
        raise RuntimeError(
            "Development/test DATABASE_URL must target a local database whose name marks it as test, dev, local, or disposable "
            f"(local_host={host in LOCAL_DATABASE_HOSTS}, disposable_database={bool(DISPOSABLE_DATABASE_NAME.search(database))})."
        )