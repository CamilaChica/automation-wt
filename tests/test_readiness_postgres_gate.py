import os
from unittest.mock import Mock

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