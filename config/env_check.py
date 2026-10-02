"""Fail-closed validation for production secrets and service configuration."""

from __future__ import annotations

import os
from typing import Iterable


REQUIRED_PRODUCTION_ENV = ("DATABASE_URL", "WT_AUTH_SECRET")


def _enabled(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


def missing_environment(names: Iterable[str] | None = None) -> list[str]:
    required = list(REQUIRED_PRODUCTION_ENV if names is None else names)
    missing = [name for name in required if not os.getenv(name, "").strip()]

    if names is None and _enabled("EMAIL_SEND_ENABLED"):
        graph_credentials = (
            "AZURE_TENANT_ID",
            "AZURE_CLIENT_ID",
            "AZURE_CLIENT_SECRET",
        )
        smtp_credentials = (
            "SALES_EMAIL_USERNAME",
            "SALES_EMAIL_PASSWORD",
            "PURCHASING_EMAIL_USERNAME",
            "PURCHASING_EMAIL_PASSWORD",
        )
        graph_ready = all(os.getenv(name, "").strip() for name in graph_credentials)
        smtp_ready = all(os.getenv(name, "").strip() for name in smtp_credentials)
        if not (graph_ready or smtp_ready):
            missing.append(
                "EMAIL_SEND_ENABLED requires Azure Graph credentials or both mailbox credentials"
            )

    if names is None and _enabled("TWILIO_ENABLED"):
        missing.extend(
            name
            for name in (
                "TWILIO_ACCOUNT_SID",
                "TWILIO_AUTH_TOKEN",
                "TWILIO_FROM_PHONE_NUMBER",
            )
            if not os.getenv(name, "").strip()
        )

    return sorted(set(missing))


def validate_production_environment() -> None:
    if os.getenv("WT_ENV", "development").strip().lower() != "production":
        return

    missing = missing_environment()
    database_url = os.getenv("DATABASE_URL", "").strip().lower()
    invalid: list[str] = []
    if database_url and not database_url.startswith(("postgresql://", "postgresql+asyncpg://")):
        invalid.append("DATABASE_URL must use PostgreSQL")
    auth_secret = os.getenv("WT_AUTH_SECRET", "").strip()
    if auth_secret and len(auth_secret) < 32:
        invalid.append("WT_AUTH_SECRET must be at least 32 characters")

    if missing or invalid:
        details = "; ".join([*(f"missing {name}" for name in missing), *invalid])
        raise SystemExit(f"Production environment validation failed: {details}")


if __name__ == "__main__":
    os.environ["WT_ENV"] = "production"
    validate_production_environment()
    print("PRODUCTION_ENV=READY")
