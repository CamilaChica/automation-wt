"""Back up the SQLite databases used by the application."""

import os
import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

try:
    from azure.storage.blob import BlobServiceClient
except ImportError:  # pragma: no cover - optional until external backups are enabled
    BlobServiceClient = None


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)
BACKUP_DIR = Path(os.getenv("SQLITE_BACKUP_DIR", str(ROOT / "backups")))
DATABASES = {
    "operations": Path(os.getenv("OPERATIONS_DB_PATH", str(ROOT / "data" / "operations.db"))),
    "supplier_email": Path(os.getenv("SUPPLIER_DATABASE_PATH", str(ROOT / "data" / "supplier_email_store.db"))),
    "auth": Path(os.getenv("WT_AUTH_DB", str(ROOT / "data" / "winged_tycoons_auth.db"))),
}


def backup_database(name: str, source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(source)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()
    return True


def archive_backup(source_dir: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for database in source_dir.glob("*.db"):
            archive.write(database, database.name)


def upload_to_azure(archive_path: Path) -> str | None:
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
    container_name = os.getenv("AZURE_STORAGE_CONTAINER", "winged-tycoons-backups").strip()
    if not connection_string:
        return None
    if BlobServiceClient is None:
        raise RuntimeError("azure-storage-blob is required when Azure backups are enabled.")

    blob_service = BlobServiceClient.from_connection_string(connection_string)
    container = blob_service.get_container_client(container_name)
    try:
        container.create_container()
    except Exception as exc:
        if "ContainerAlreadyExists" not in str(exc):
            raise
    blob_name = archive_path.name
    with archive_path.open("rb") as stream:
        container.upload_blob(name=blob_name, data=stream, overwrite=True)
    return f"{container_name}/{blob_name}"


def main() -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target_dir = BACKUP_DIR / timestamp
    target_dir.mkdir(parents=True, exist_ok=True)
    backed_up = []
    for name, source in DATABASES.items():
        destination = target_dir / f"{name}.db"
        if backup_database(name, source, destination):
            backed_up.append(str(destination))
    archive_path = BACKUP_DIR / f"winged-tycoons-{timestamp}.zip"
    archive_backup(target_dir, archive_path)
    uploaded_blob = upload_to_azure(archive_path)
    print(f"Backed up {len(backed_up)} database(s) to {target_dir}")
    for path in backed_up:
        print(path)
    if uploaded_blob:
        print(f"Uploaded external backup: {uploaded_blob}")


if __name__ == "__main__":
    main()
