from fastapi.testclient import TestClient

from api.main import _rate_limit_events, app


def test_sensitive_route_rate_limit_returns_retry_after(monkeypatch):
    from api.main import _RATE_LIMIT_RULES

    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setitem(_RATE_LIMIT_RULES, "/api/catalog/search", (3, 60))
    _rate_limit_events.clear()
    client = TestClient(app)

    responses = [client.get("/api/catalog/search", params={"q": "PN-1"}) for _ in range(4)]

    assert responses[-1].status_code == 429
    assert responses[-1].headers["retry-after"]


def test_rate_limit_can_be_disabled_for_controlled_local_tests(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("WT_AUTH_ENV", "development")
    monkeypatch.setattr("api.main.request_otp", lambda *_args: ("test-challenge", "123456"))
    _rate_limit_events.clear()
    client = TestClient(app)

    response = client.post("/api/auth/otp/request", json={"email": "fresh-buyer@example.com", "role": "ROLE_CUSTOMER"})

    assert response.status_code != 429