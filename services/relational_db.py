import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Generator

DEFAULT_DB_PATH = Path("data/winged_tycoons_mvp.db")
MIGRATION_PATH = Path("src/db/migrations/002_relational_schema.sql")


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def normalize_part_number(raw_part_number: str) -> str:
    return re.sub(r"\s+", "", raw_part_number.strip()).upper()


@contextmanager
def db_connection(db_path: Path = DEFAULT_DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def run_migration(connection: sqlite3.Connection) -> None:
    migration_sql = MIGRATION_PATH.read_text(encoding="utf-8")
    connection.executescript(migration_sql)


def ensure_schema(db_path: Path = DEFAULT_DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with db_connection(db_path) as connection:
        run_migration(connection)


def _insert_supplier(connection: sqlite3.Connection, name: str, email: str, phone: str) -> str:
    supplier_id = f"SUP-{uuid.uuid4().hex[:8].upper()}"
    connection.execute(
        """
        INSERT INTO suppliers (id, name, email, phone, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (supplier_id, name, email.lower(), phone, utc_now_iso()),
    )
    return supplier_id


def _insert_client(connection: sqlite3.Connection, company_name: str, email: str, phone: str, account_status: str = "ACTIVE") -> str:
    client_id = f"CLI-{uuid.uuid4().hex[:8].upper()}"
    connection.execute(
        """
        INSERT INTO clients (id, company_name, email, phone, account_status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (client_id, company_name, email.lower(), phone, account_status, utc_now_iso()),
    )
    return client_id


def _insert_inventory_item(
    connection: sqlite3.Connection,
    supplier_id: str,
    raw_part_number: str,
    description: str,
    condition: str,
    quantity_available: int,
    unit_cost_usd: float,
    location: str,
    lead_time_days: int,
    source_email_id: str,
) -> str:
    inventory_id = f"INV-{uuid.uuid4().hex[:8].upper()}"
    clean_part = normalize_part_number(raw_part_number)
    now = utc_now_iso()
    connection.execute(
        """
        INSERT INTO inventory_items (
            id, supplier_id, raw_part_number, clean_part_number, description, condition,
            quantity_available, unit_cost_usd, location, lead_time_days, source_email_id, last_updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            inventory_id,
            supplier_id,
            raw_part_number,
            clean_part,
            description,
            condition.upper(),
            quantity_available,
            unit_cost_usd,
            location,
            lead_time_days,
            source_email_id,
            now,
        ),
    )
    return inventory_id


def _insert_client_rfq(
    connection: sqlite3.Connection,
    client_id: str,
    clean_part_number: str,
    requested_quantity: int,
    status: str,
    inventory_item_id: str | None = None,
) -> str:
    rfq_id = f"CRFQ-{uuid.uuid4().hex[:8].upper()}"
    connection.execute(
        """
        INSERT INTO client_rfqs (
            id, client_id, inventory_item_id, clean_part_number, requested_quantity, status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (rfq_id, client_id, inventory_item_id, clean_part_number, requested_quantity, status, utc_now_iso()),
    )
    return rfq_id


def _insert_purchase_order(connection: sqlite3.Connection, client_rfq_id: str, supplier_id: str, po_status: str, total_amount_usd: float) -> str:
    po_id = f"PO-{uuid.uuid4().hex[:8].upper()}"
    connection.execute(
        """
        INSERT INTO purchase_orders (id, client_rfq_id, supplier_id, po_status, total_amount_usd, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (po_id, client_rfq_id, supplier_id, po_status, total_amount_usd, utc_now_iso()),
    )
    return po_id


def seed_relational_mock_data(db_path: Path = DEFAULT_DB_PATH) -> None:
    ensure_schema(db_path)
    with db_connection(db_path) as connection:
        existing = connection.execute("SELECT COUNT(1) AS count FROM suppliers").fetchone()["count"]
        if existing > 0:
            return

        sup_apex = _insert_supplier(connection, "Apex Aero Components", "quotes@apexaero.com", "+1-305-555-0142")
        sup_vanguard = _insert_supplier(connection, "Vanguard Aviation Spares", "procurement@vanguardspares.com", "+1-972-555-0378")

        cli_delta = _insert_client(connection, "Delta MRO Services", "procurement@deltamro.com", "+1-404-555-0101")
        cli_united = _insert_client(connection, "United Aerospace", "parts@unitedaero.com", "+1-312-555-0110")

        inv_1 = _insert_inventory_item(
            connection,
            supplier_id=sup_apex,
            raw_part_number="060-1234-00",
            description="Hydraulic Pump Assembly",
            condition="NE",
            quantity_available=3,
            unit_cost_usd=1025.0,
            location="Aisle 3, Bin B4",
            lead_time_days=2,
            source_email_id="seed-email-001",
        )
        _insert_inventory_item(
            connection,
            supplier_id=sup_vanguard,
            raw_part_number="456-789-OH",
            description="Actuator Overhaul Unit",
            condition="OH",
            quantity_available=2,
            unit_cost_usd=465.0,
            location="Aisle 12, Bin C2",
            lead_time_days=5,
            source_email_id="seed-email-002",
        )

        rfq_pending = _insert_client_rfq(connection, cli_delta, "060-1234-00", 2, "PENDING_QUOTE", inv_1)
        rfq_po_pending = _insert_client_rfq(connection, cli_delta, "456-789-OH", 1, "PO_PENDING")
        rfq_solved = _insert_client_rfq(connection, cli_united, "060-1234-00", 1, "SOLVED", inv_1)

        _insert_purchase_order(connection, rfq_pending, sup_apex, "PENDING_PROCUREMENT", 2050.0)
        _insert_purchase_order(connection, rfq_po_pending, sup_vanguard, "ISSUED_TO_VENDOR", 465.0)
        _insert_purchase_order(connection, rfq_solved, sup_apex, "COMPLETED", 1025.0)
