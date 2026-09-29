import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient

from api.main import app


def test_production_readiness_requires_postgres_mirroring(monkeypatch):
    monkeypatch.setenv("WT_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert "DATABASE_URL" in response.json()["detail"]


def test_readiness_does_not_expose_database_exception_details(monkeypatch):
    monkeypatch.setenv("WT_ENV", "development")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        "api.main.db_service.list_rfqs",
        Mock(side_effect=RuntimeError("SELECT * FROM users; password=do-not-leak")),
    )

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == "Database readiness check failed."
    assert "SELECT" not in response.text
    assert "password" not in response.text


async def test_production_readiness_uses_async_repositories_without_sync_db_service(monkeypatch):
    from api import main

    class Session:
        pass

    class RFQRepository:
        async def list_operational_records(self, domain):
            assert domain == "rfqs"
            return {}

        async def list(self):
            return []

    class Repositories:
        rfq = RFQRepository()

        async def check_readiness(self):
            return {"inventory": True, "rfq": True, "supplier": True, "quote": True}

    class Engine:
        async def dispose(self):
            return None

    @asynccontextmanager
    async def fake_session_scope(_engine):
        yield Session()

    monkeypatch.setenv("WT_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://db.example/production")
    monkeypatch.setenv("INVENTORY_INGESTION_POSTGRES_ENABLED", "true")
    monkeypatch.setenv("OPERATIONAL_POSTGRES_RUNTIME_ENABLED", "true")
    monkeypatch.setattr(main, "create_engine_from_environment", Engine)
    monkeypatch.setattr(main, "preflight_database", AsyncMock(return_value=None))
    monkeypatch.setattr(main, "check_migration_state", AsyncMock(return_value={"ready": True}))
    monkeypatch.setattr(main, "session_scope", fake_session_scope)
    monkeypatch.setattr(main, "create_operational_repositories", Mock(return_value=Repositories()))
    monkeypatch.setattr(main, "persistence_status", Mock(return_value={
        "inventory_postgres_mirror_enabled": True,
        "full_operational_persistence_ready": True,
    }))
    monkeypatch.setattr(main.db_service, "list_rfqs", Mock(side_effect=AssertionError("sync db_service used")))

    result = await main.ready()

    assert result["status"] == "ready"


async def test_rfq_list_route_uses_async_db_service_when_session_is_available(monkeypatch):
    from api import main
    from models.db_models import RFQ

    rfq = RFQ(
        id="RFQ-ASYNC-LIST",
        customer_name="Async Buyer",
        customer_email="buyer@example.test",
        raw_text="Need part 123",
    )
    async_list = AsyncMock(return_value=[rfq])
    monkeypatch.setattr(main.db_service, "list_rfqs_async", async_list)

    result = await main.list_rfqs(
        user={"role": "ROLE_ADMIN", "email": "admin@example.test"},
        session=object(),
    )

    assert [item.id for item in result] == [rfq.id]
    async_list.assert_awaited_once()