import pytest


@pytest.fixture(autouse=True)
def disable_external_email_for_tests(monkeypatch):
    """Keep local .env values from enabling real outbound email in tests."""
    monkeypatch.setenv("EMAIL_SEND_ENABLED", "false")
