import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.db_service import db_service

DEFAULT_DB_PATH = "data/app.db" if os.name == "nt" else "/var/data/app.db"
DB_PATH = os.getenv("MIGRATION_SQLITE_PATH", DEFAULT_DB_PATH)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IntegrationDbService:
    def __init__(self) -> None:
        self._ensure_parent()
        self._init_schema()
        self.sync_mock_reference_data()

    def _ensure_parent(self) -> None:
        parent = Path(DB_PATH).parent
        parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(DB_PATH)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS inventory_items (
                    id TEXT PRIMARY KEY,
                    part_number TEXT NOT NULL,
                    serial_number TEXT,
                    quantity_available INTEGER NOT NULL,
                    condition_code TEXT NOT NULL,
                    warehouse_location TEXT,
                    unit_cost REAL NOT NULL DEFAULT 0,
                    certificate_type TEXT NOT NULL,
                    has_full_trace INTEGER NOT NULL DEFAULT 1,
                    supplier_id TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS suppliers (
                    id TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    contact_name TEXT,
                    email TEXT,
                    email_quotes TEXT,
                    approval_status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS client_rfqs (
                    id TEXT PRIMARY KEY,
                    customer_name TEXT NOT NULL,
                    customer_email TEXT NOT NULL,
                    part_number TEXT,
                    quantity INTEGER,
                    status TEXT NOT NULL,
                    quote_id TEXT,
                    quote_total REAL,
                    po_status TEXT NOT NULL DEFAULT 'Pending',
                    updated_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS purchase_orders (
                    id TEXT PRIMARY KEY,
                    rfq_id TEXT NOT NULL,
                    quote_id TEXT NOT NULL,
                    supplier_id TEXT,
                    supplier_name TEXT NOT NULL,
                    part_number TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS csv_ingestion_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    details TEXT,
                    processed_at TEXT NOT NULL
                );
                """
            )

    def sync_mock_reference_data(self) -> None:
        with self._connect() as connection:
            for supplier in db_service.suppliers.values():
                connection.execute(
                    """
                    INSERT INTO suppliers (id, company_name, contact_name, email, email_quotes, approval_status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        company_name=excluded.company_name,
                        contact_name=excluded.contact_name,
                        email=excluded.email,
                        email_quotes=excluded.email_quotes,
                        approval_status=excluded.approval_status,
                        updated_at=excluded.updated_at
                    """,
                    (
                        supplier.id,
                        supplier.company_name,
                        supplier.contact_name,
                        supplier.email,
                        supplier.email_quotes,
                        supplier.approval_status,
                        _utc_now(),
                    ),
                )
            for item in db_service.inventory.values():
                connection.execute(
                    """
                    INSERT INTO inventory_items (
                        id, part_number, serial_number, quantity_available, condition_code, warehouse_location,
                        unit_cost, certificate_type, has_full_trace, supplier_id, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        part_number=excluded.part_number,
                        serial_number=excluded.serial_number,
                        quantity_available=excluded.quantity_available,
                        condition_code=excluded.condition_code,
                        warehouse_location=excluded.warehouse_location,
                        unit_cost=excluded.unit_cost,
                        certificate_type=excluded.certificate_type,
                        has_full_trace=excluded.has_full_trace,
                        supplier_id=excluded.supplier_id,
                        updated_at=excluded.updated_at
                    """,
                    (
                        item.id,
                        item.part_number,
                        item.serial_number,
                        item.quantity_available,
                        item.condition_code,
                        item.warehouse_location,
                        item.unit_cost,
                        item.certificate_type,
                        1 if item.has_full_trace else 0,
                        None,
                        _utc_now(),
                    ),
                )

    def upsert_supplier_inventory_email(self, parsed: Dict[str, Any]) -> None:
        supplier_id = parsed["supplier_id"]
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO suppliers (id, company_name, contact_name, email, email_quotes, approval_status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    company_name=excluded.company_name,
                    contact_name=excluded.contact_name,
                    email=excluded.email,
                    email_quotes=excluded.email_quotes,
                    approval_status=excluded.approval_status,
                    updated_at=excluded.updated_at
                """,
                (
                    supplier_id,
                    parsed["supplier_name"],
                    parsed["contact_name"],
                    parsed["contact_email"],
                    parsed["contact_email"],
                    "Approved",
                    _utc_now(),
                ),
            )
            connection.execute(
                """
                INSERT INTO inventory_items (
                    id, part_number, serial_number, quantity_available, condition_code, warehouse_location,
                    unit_cost, certificate_type, has_full_trace, supplier_id, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    quantity_available=excluded.quantity_available,
                    condition_code=excluded.condition_code,
                    unit_cost=excluded.unit_cost,
                    certificate_type=excluded.certificate_type,
                    has_full_trace=excluded.has_full_trace,
                    supplier_id=excluded.supplier_id,
                    updated_at=excluded.updated_at
                """,
                (
                    parsed["inventory_id"],
                    parsed["part_number"],
                    parsed.get("serial_number"),
                    parsed["quantity"],
                    parsed["condition_code"],
                    parsed.get("warehouse_location", "Supplier Feed"),
                    parsed["unit_cost"],
                    parsed["certificate_type"],
                    1 if parsed.get("has_full_trace", True) else 0,
                    supplier_id,
                    _utc_now(),
                ),
            )
            connection.execute(
                """
                INSERT INTO csv_ingestion_logs (source_name, status, details, processed_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    parsed.get("source", "purchasing_email"),
                    "success",
                    f"Upserted supplier {supplier_id} part {parsed['part_number']}",
                    _utc_now(),
                ),
            )

    def get_catalog_items(self, query: str) -> List[Dict[str, Any]]:
        normalized = query.strip().lower()
        sql = """
            SELECT part_number, condition_code, SUM(quantity_available) AS quantity_available, certificate_type, MIN(has_full_trace) AS has_full_trace
            FROM inventory_items
            WHERE (? = '' OR LOWER(part_number) LIKE ?)
            GROUP BY part_number, condition_code, certificate_type
            ORDER BY part_number
        """
        wildcard = f"%{normalized}%"
        with self._connect() as connection:
            rows = connection.execute(sql, (normalized, wildcard)).fetchall()
        return [
            {
                "part_number": row["part_number"],
                "condition_code": row["condition_code"],
                "quantity_available": int(row["quantity_available"] or 0),
                "certificate_type": row["certificate_type"],
                "has_full_trace": bool(row["has_full_trace"]),
            }
            for row in rows
        ]

    def upsert_client_rfq(
        self,
        rfq_id: str,
        customer_name: str,
        customer_email: str,
        part_number: Optional[str],
        quantity: Optional[int],
        status: str,
        quote_id: Optional[str],
        quote_total: Optional[float],
        po_status: str,
    ) -> None:
        with self._connect() as connection:
            existing = connection.execute("SELECT created_at FROM client_rfqs WHERE id = ?", (rfq_id,)).fetchone()
            created_at = existing["created_at"] if existing else _utc_now()
            connection.execute(
                """
                INSERT INTO client_rfqs (id, customer_name, customer_email, part_number, quantity, status, quote_id, quote_total, po_status, updated_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    customer_name=excluded.customer_name,
                    customer_email=excluded.customer_email,
                    part_number=excluded.part_number,
                    quantity=excluded.quantity,
                    status=excluded.status,
                    quote_id=excluded.quote_id,
                    quote_total=excluded.quote_total,
                    po_status=excluded.po_status,
                    updated_at=excluded.updated_at
                """,
                (
                    rfq_id,
                    customer_name,
                    customer_email,
                    part_number,
                    quantity,
                    status,
                    quote_id,
                    quote_total,
                    po_status,
                    _utc_now(),
                    created_at,
                ),
            )

    def list_client_rfqs(self) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, customer_name, customer_email, part_number, quantity, status, quote_id, quote_total, po_status, updated_at
                FROM client_rfqs
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def create_purchase_order(
        self,
        po_id: str,
        rfq_id: str,
        quote_id: str,
        supplier_id: Optional[str],
        supplier_name: str,
        part_number: str,
        quantity: int,
        status: str = "PO Pending",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO purchase_orders (id, rfq_id, quote_id, supplier_id, supplier_name, part_number, quantity, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (po_id, rfq_id, quote_id, supplier_id, supplier_name, part_number, quantity, status, _utc_now()),
            )

    def list_active_purchase_orders(self) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, rfq_id, quote_id, supplier_id, supplier_name, part_number, quantity, status, created_at
                FROM purchase_orders
                WHERE status IN ('PO Pending', 'PO Sent', 'In Fulfillment')
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_supplier_inventory(self) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT i.id, i.part_number, i.quantity_available, i.condition_code, i.certificate_type, i.unit_cost,
                       i.supplier_id, COALESCE(s.company_name, 'Winged Tycoons Internal') AS supplier_name
                FROM inventory_items i
                LEFT JOIN suppliers s ON s.id = i.supplier_id
                ORDER BY i.part_number
                """
            ).fetchall()
        return [dict(row) for row in rows]


integration_db_service = IntegrationDbService()
