"""Integration-test options for optional external-provider verification."""

import os


def pytest_addoption(parser):
    parser.addoption(
        "--run-live-llm",
        action="store_true",
        default=False,
        help="Run opt-in live OpenAI/Anthropic/Gemini verification tests.",
    )


def pytest_configure(config):
    if config.getoption("--run-live-llm"):
        os.environ["RUN_LIVE_LLM"] = "1"
