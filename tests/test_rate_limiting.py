from fastapi.testclient import TestClient

from api.main import _rate_limit_events, app


def test_sensitive_route_rate_limit_returns_retry_after(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    _rate_limit_events.clear()
    client = TestClient(app)

    responses = [client.post("/api/auth/otp/request", json={"email": "buyer@example.com", "role": "ROLE_CUSTOMER"}) for _ in range(4)]

    assert responses[-1].status_code == 429
    assert responses[-1].headers["retry-after"]


def test_rate_limit_can_be_disabled_for_controlled_local_tests(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    _rate_limit_events.clear()
    client = TestClient(app)

    response = client.post("/api/auth/otp/request", json={"email": "fresh-buyer@example.com", "role": "ROLE_CUSTOMER"})

    assert response.status_code != 429