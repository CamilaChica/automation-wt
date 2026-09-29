from __future__ import annotations

import os
from urllib.parse import urlsplit


MUTATING_COMMANDS = frozenset({"upgrade", "downgrade", "stamp", "ensure_version"})
LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def normalize_alembic_command(command: object) -> str | None:
    while isinstance(command, (list, tuple)):
        if not command:
            return None
        command = command[0]
    if callable(command):
        command = getattr(command, "__name__", None)
    return command if isinstance(command, str) else None


def is_read_only_alembic_command(command: object) -> bool:
    command = normalize_alembic_command(command)
    return command in {"current", "check", "history", "heads", "branches", "show"}


def validate_alembic_target(command: object, database_url: str) -> None:
    command = normalize_alembic_command(command)
    if command not in MUTATING_COMMANDS:
        return
    host = (urlsplit(database_url).hostname or "").lower()
    if not host:
        raise RuntimeError("A database host is required for Alembic mutations.")
    if host not in LOCAL_DATABASE_HOSTS and os.getenv("ALLOW_REMOTE_ALEMBIC_MIGRATIONS", "").lower() != "true":
        raise RuntimeError("Remote Alembic migrations require ALLOW_REMOTE_ALEMBIC_MIGRATIONS=true.")
    if host.endswith(".render.com") and os.getenv("ALLOW_PRODUCTION_ALEMBIC_MIGRATIONS", "").lower() != "true":
        raise RuntimeError("Render migrations require ALLOW_PRODUCTION_ALEMBIC_MIGRATIONS=true.")