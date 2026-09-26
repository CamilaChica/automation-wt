import asyncio
from unittest.mock import AsyncMock

from repositories.idempotency_repository import IdempotencyRepository


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


def test_idempotency_claim_uses_atomic_conflict_safe_insert():
    session = AsyncMock()
    session.execute.return_value = _Result("graph-message-1")
    repository = IdempotencyRepository(session)

    claimed = asyncio.run(repository.claim("graph-message-1", "sales"))

    assert claimed is True
    statement = session.execute.call_args.args[0]
    sql = str(statement.compile(dialect=__import__("sqlalchemy.dialects.postgresql").dialects.postgresql.dialect()))
    assert "ON CONFLICT (message_id) DO NOTHING" in sql
    session.flush.assert_awaited_once()


def test_duplicate_message_claim_returns_false():
    session = AsyncMock()
    session.execute.return_value = _Result(None)
    repository = IdempotencyRepository(session)

    claimed = asyncio.run(repository.claim("graph-message-1", "sales"))

    assert claimed is False
    session.flush.assert_awaited_once()
