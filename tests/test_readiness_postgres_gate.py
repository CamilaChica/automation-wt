import os

from fastapi.testclient import TestClient

from api.main import app


def test_production_readiness_requires_postgres_mirroring(monkeypatch):
    monkeypatch.setenv("WT_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert "DATABASE_URL" in response.json()["detail"]