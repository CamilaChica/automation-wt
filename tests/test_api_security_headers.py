from fastapi.testclient import TestClient

from api.main import _build_allowed_origins, app


def test_health_endpoint_returns_security_headers():
    response = TestClient(app).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]
    assert float(response.headers["x-response-time-ms"]) >= 0
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_internal_auth_preflight_allows_post_and_auth_headers():
    response = TestClient(app).options(
        "/api/auth/otp/request",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,x-internal-role",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in response.headers["access-control-allow-methods"]
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed_headers
    assert "content-type" in allowed_headers
    assert "x-internal-role" in allowed_headers


def test_production_cors_excludes_development_origins():
    origins = _build_allowed_origins({"https://api.example.com"}, "production")

    assert "https://api.example.com" in origins
    assert "https://portal.wingedtycoons.com" in origins
    assert "http://localhost:5173" not in origins
    assert "http://127.0.0.1:3000" not in origins


def test_production_cors_rejects_insecure_or_local_configured_origins():
    for origin in ("http://app.example.com", "http://localhost:5173", "https://127.0.0.1"):
        try:
            _build_allowed_origins({origin}, "production")
        except RuntimeError as error:
            assert "HTTPS public origins" in str(error)
        else:
            raise AssertionError(f"Production accepted an unsafe origin: {origin}")