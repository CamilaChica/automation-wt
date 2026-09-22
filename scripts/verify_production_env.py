"""Validate production environment presence without printing secret values."""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv_if_present() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv_if_present()

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
    "MICROSOFT_GRAPH_TENANT_ID",
    "AZURE_STORAGE_CONNECTION_STRING",
    "AZURE_STORAGE_CONTAINER",
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
