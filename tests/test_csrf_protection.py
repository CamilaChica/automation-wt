from fastapi.testclient import TestClient

from api.main import app


def test_cookie_session_mutation_requires_csrf_token(monkeypatch):
    client = TestClient(app)
    client.cookies.set("wt_session", "session-token")
    client.cookies.set("wt_csrf", "csrf-token")

    response = client.post("/api/rfqs/intake", json={"raw_text": "test"})
    assert response.status_code == 403


def test_bearer_clients_are_not_blocked_by_cookie_csrf_layer(monkeypatch):
    client = TestClient(app)
    response = client.post(
        "/api/rfqs/intake",
        json={"raw_text": "test"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code != 403