import os

import pytest
from fastapi.testclient import TestClient


def pytest_addoption(parser):
    parser.addoption(
        "--run-live-llm",
        action="store_true",
        default=False,
        help="Allow tests marked live_llm to contact configured external LLM providers.",
    )
    parser.addoption(
        "--run-staging-integration",
        action="store_true",
        default=False,
        help="Allow tests marked staging to create RFQs and send to staging allowlisted inboxes.",
    )
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


def pytest_collection_modifyitems(config, items):
    live_llm_enabled = (
        config.getoption("--run-live-llm")
        or os.getenv("RUN_LIVE_LLM", "").strip() == "1"
    )
    staging_enabled = (
        config.getoption("--run-staging-integration")
        or os.getenv("RUN_STAGING_INTEGRATION", "").strip() == "1"
    )
    for item in items:
        if "live_llm" in item.keywords and not live_llm_enabled:
            item.add_marker(pytest.mark.skip(
                reason="Live LLM calls are opt-in; pass --run-live-llm or set RUN_LIVE_LLM=1."
            ))
        if "staging" in item.keywords and not staging_enabled:
            item.add_marker(pytest.mark.skip(
                reason="Staging integration tests are opt-in; pass --run-staging-integration or set RUN_STAGING_INTEGRATION=1."
            ))


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
