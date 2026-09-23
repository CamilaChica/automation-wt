from pathlib import Path
from unittest.mock import patch

from services.supplier_database import _writable_database_path


def test_supplier_database_falls_back_to_tmp_when_configured_path_is_unwritable():
    configured = Path("/var/data/supplier_email_store.db")
    with patch.object(Path, "touch", side_effect=PermissionError("read-only mount")):
        resolved = _writable_database_path(configured)

    assert resolved == Path("/tmp/data/supplier_email_store.db")
