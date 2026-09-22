"""Validate production environment presence without printing secret values."""

from __future__ import annotations

import os
import sys


REQUIRED = (
    "WT_AUTH_SECRET",
    "DATABASE_URL",
    "OPENAI_API_KEY",
    "LLM_LIVE_ENABLED",
    "LLM_DEFAULT_PROVIDER",
    "LLM_TASK_PROVIDERS",
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "GRAPH_MAILBOX_USER",
    "AZURE_STORAGE_CONNECTION_STRING",
    "PUBLIC_APP_URL",
    "FRONTEND_ORIGIN",
    "EMAIL_SEND_ENABLED",
)

OPTIONAL_WHEN_ENABLED = {
    "TWILIO_ENABLED": ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"),
    "FREIGHT_ENABLED": ("FREIGHT_API_BASE_URL", "FREIGHT_API_KEY"),
}


def main() -> int:
    missing = [name for name in REQUIRED if not os.getenv(name, "").strip()]
    invalid = []
    if os.getenv("WT_AUTH_ENV", "").strip().lower() != "production":
        invalid.append("WT_AUTH_ENV must equal production")
    if len(os.getenv("WT_AUTH_SECRET", "")) < 32:
        invalid.append("WT_AUTH_SECRET must be at least 32 characters")
    if os.getenv("LLM_LIVE_ENABLED", "").strip().lower() not in {"1", "true", "yes", "on"}:
        invalid.append("LLM_LIVE_ENABLED must be true")
    if os.getenv("EMAIL_SEND_ENABLED", "").strip().lower() not in {"1", "true", "yes", "on"}:
        invalid.append("EMAIL_SEND_ENABLED must be true")

    for flag, dependencies in OPTIONAL_WHEN_ENABLED.items():
        if os.getenv(flag, "").strip().lower() in {"1", "true", "yes", "on"}:
            missing.extend(name for name in dependencies if not os.getenv(name, "").strip())

    if missing or invalid:
        print("PRODUCTION_ENV=FAILED")
        for name in sorted(set(missing)):
            print(f"MISSING={name}")
        for message in invalid:
            print(f"INVALID={message}")
        return 1

    print("PRODUCTION_ENV=READY")
    print("SECRET_VALUES=NOT_PRINTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
