"""Production preflight checks without printing secret values."""

import os
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent


def configured(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def main() -> int:
    load_dotenv(ROOT / ".env")
    required = [
        "WT_AUTH_SECRET",
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
        "GRAPH_MAILBOX_USER",
        "AFTERSHIP_API_KEY",
        "CARRIER_WEBHOOK_SECRET",
        "PUBLIC_APP_URL",
        "PURCHASE_ORDER_NOTIFICATION_EMAIL",
    ]
    missing = [name for name in required if not configured(name)]
    if os.getenv("WT_AUTH_ENV", "development") == "production":
        auth_secret = os.getenv("WT_AUTH_SECRET", "")
        if auth_secret in {"development-only-change-this-secret", "replace-with-a-long-random-secret"} or len(auth_secret) < 32:
            missing.append("WT_AUTH_SECRET (use a random value of at least 32 characters)")

    database_paths = [
        Path(os.getenv("OPERATIONS_DB_PATH", str(ROOT / "data" / "operations.db"))),
        Path(os.getenv("SUPPLIER_DATABASE_PATH", str(ROOT / "data" / "supplier_email_store.db"))),
        Path(os.getenv("WT_AUTH_DB", str(ROOT / "data" / "winged_tycoons_auth.db"))),
    ]
    for path in database_paths:
        if not path.parent.exists():
            missing.append(f"database directory: {path.parent}")

    if missing:
        print("PREFLIGHT=failed")
        for item in missing:
            print(f"MISSING={item}")
        return 1

    print("PREFLIGHT=passed")
    print("SECRET_VALUES=not_displayed")
    print(f"DATABASE_PATHS={len(database_paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
