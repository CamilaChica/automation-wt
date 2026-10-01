from fastapi.testclient import TestClient

from api.main import app


def test_mailbox_health_requires_authentication(monkeypatch):
    monkeypatch.setattr("api.main.health_check_mailboxes", lambda _mailboxes: {})

    response = TestClient(app).get("/api/internal/mailboxes/health")

    assert response.status_code == 401


def test_mailbox_health_accepts_http_only_cookie_only(internal_session, monkeypatch):
    client, _session = internal_session
    monkeypatch.setattr(
        "api.main.health_check_mailboxes",
        lambda mailboxes: {
            mailbox: {"status": "ok", "message_count": 3, "latest_subject": "private subject"}
            for mailbox in mailboxes
        },
    )

    cookie_response = client.get("/api/internal/mailboxes/health")
    expected = {
        "sales_mailbox": "ok",
        "purchasing_mailbox": "ok",
        "authenticated_user": "camila@wingedtycoons.com",
    }

    assert cookie_response.status_code == 200
    assert cookie_response.json() == expected