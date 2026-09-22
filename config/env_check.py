"""Fail-closed validation for production secrets and service configuration."""

from __future__ import annotations

import os
from typing import Iterable


REQUIRED_PRODUCTION_ENV = (
    "DATABASE_URL",
    "MICROSOFT_TENANT_ID",
    "MICROSOFT_CLIENT_ID",
    "MICROSOFT_CLIENT_SECRET",
    "MICROSOFT_MAILBOX_ADDRESS",
    "AWS_S3_BUCKET_NAME",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM_PHONE_NUMBER",
)


def missing_environment(names: Iterable[str] = REQUIRED_PRODUCTION_ENV) -> list[str]:
    return sorted(name for name in names if not os.getenv(name, "").strip())


def validate_production_environment() -> None:
    if os.getenv("WT_ENV", "development").strip().lower() != "production":
        return

    missing = missing_environment()
    database_url = os.getenv("DATABASE_URL", "").strip().lower()
    invalid: list[str] = []
    if database_url and not database_url.startswith(("postgresql://", "postgresql+asyncpg://")):
        invalid.append("DATABASE_URL must use PostgreSQL")

    if missing or invalid:
        details = "; ".join([*(f"missing {name}" for name in missing), *invalid])
        raise SystemExit(f"Production environment validation failed: {details}")


if __name__ == "__main__":
    os.environ["WT_ENV"] = "production"
    validate_production_environment()
    print("PRODUCTION_ENV=READY")
