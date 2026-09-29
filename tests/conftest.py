import os

import pytest
from fastapi.testclient import TestClient


def pytest_addoption(parser):
    parser.addoption(
        "--live-telemetry",
        action="store_true",
        default=False,
        help="Run extraction calibration against configured live model endpoints.",
    )
    parser.addoption(
        "--eval-set",
        action="store",
        default=None,
        help="Path to a de-identified JSONL or annotated EML extraction evaluation set.",
    )


@pytest.fixture(autouse=True)
def disable_external_email_for_tests(monkeypatch):
    """Keep local .env values from enabling real outbound email in tests."""
    monkeypatch.setenv("EMAIL_SEND_ENABLED", "false")


@pytest.fixture
def internal_session(tmp_path, monkeypatch):
    import api.auth as auth
    from api.main import app

    monkeypatch.setattr(auth, "AUTH_DB_PATH", str(tmp_path / "auth.db"))
    auth.init_auth_db()
    challenge_id, code = auth.request_otp("camila@wingedtycoons.com", "ROLE_INTERNAL")
    client = TestClient(app)
    response = client.post(
        "/api/auth/otp/verify",
        json={"challenge_id": challenge_id, "code": code},
    )
    assert response.status_code == 200
    return client, response.json()
