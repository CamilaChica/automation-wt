from fastapi.testclient import TestClient

from api.main import app


def test_health_endpoint_returns_security_headers():
    response = TestClient(app).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]
    assert float(response.headers["x-response-time-ms"]) >= 0
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"