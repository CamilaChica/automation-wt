def test_otp_verification_returns_identity_and_http_only_session_cookie(internal_session):
    client, session = internal_session

    assert session["email"] == "camila@wingedtycoons.com"
    assert session["role"] == "ROLE_ADMIN"
    assert "access_token" not in session
    assert "token_type" not in session
    assert client.cookies.get("wt_session")


def test_invalid_bearer_does_not_fall_back_to_valid_session_cookie(internal_session):
    client, _session = internal_session

    response = client.get(
        "/api/internal/mailboxes/health",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401