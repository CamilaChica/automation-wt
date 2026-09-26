import pytest


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
