from pathlib import Path
from typing import Any

from services.relational_db import DEFAULT_DB_PATH, db_connection, ensure_schema

SALES_DEFAULT_STATUSES = ("PENDING_QUOTE", "PO_PENDING", "SOLVED")


def get_sales_dashboard_data(
    db_path: Path = DEFAULT_DB_PATH,
    statuses: tuple[str, ...] = SALES_DEFAULT_STATUSES,
) -> dict[str, Any]:
    ensure_schema(db_path)
    placeholders = ",".join("?" for _ in statuses)
    with db_connection(db_path) as connection:
        rfqs = connection.execute(
            f"""
            SELECT
                r.id,
                r.client_id,
                c.company_name,
                c.email AS client_email,
                r.clean_part_number,
                r.requested_quantity,
                r.status,
                r.created_at,
                po.id AS purchase_order_id,
                po.po_status
            FROM client_rfqs r
            JOIN clients c ON c.id = r.client_id
            LEFT JOIN purchase_orders po ON po.client_rfq_id = r.id
            WHERE r.status IN ({placeholders})
            ORDER BY r.created_at DESC
            """,
            statuses,
        ).fetchall()

        history_rows = connection.execute(
            """
            SELECT
                c.id AS client_id,
                c.company_name,
                r.id AS rfq_id,
                r.clean_part_number,
                r.requested_quantity,
                r.status AS rfq_status,
                r.created_at,
                po.id AS purchase_order_id,
                po.po_status,
                po.total_amount_usd
            FROM clients c
            LEFT JOIN client_rfqs r ON r.client_id = c.id
            LEFT JOIN purchase_orders po ON po.client_rfq_id = r.id
            ORDER BY c.company_name ASC, r.created_at DESC
            """
        ).fetchall()

    history_by_client: dict[str, dict[str, Any]] = {}
    for row in history_rows:
        client_id = str(row["client_id"])
        if client_id not in history_by_client:
            history_by_client[client_id] = {
                "client_id": client_id,
                "company_name": row["company_name"],
                "records": [],
            }
        if row["rfq_id"] is None:
            continue
        history_by_client[client_id]["records"].append(
            {
                "rfq_id": row["rfq_id"],
                "clean_part_number": row["clean_part_number"],
                "requested_quantity": row["requested_quantity"],
                "rfq_status": row["rfq_status"],
                "created_at": row["created_at"],
                "purchase_order_id": row["purchase_order_id"],
                "po_status": row["po_status"],
                "total_amount_usd": row["total_amount_usd"],
            }
        )

    return {
        "rfqs": [dict(row) for row in rfqs],
        "client_history": list(history_by_client.values()),
    }


def get_procurement_dashboard_data(db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    ensure_schema(db_path)
    with db_connection(db_path) as connection:
        suppliers = connection.execute(
            """
            SELECT
                s.id AS supplier_id,
                s.name,
                s.email,
                s.phone,
                i.id AS inventory_item_id,
                i.clean_part_number,
                i.condition,
                i.quantity_available,
                i.unit_cost_usd,
                i.lead_time_days,
                i.last_updated_at
            FROM suppliers s
            LEFT JOIN inventory_items i ON i.supplier_id = s.id
            ORDER BY s.name ASC, i.last_updated_at DESC
            """
        ).fetchall()

        pending_pos = connection.execute(
            """
            SELECT
                po.id,
                po.client_rfq_id,
                po.supplier_id,
                s.name AS supplier_name,
                po.po_status,
                po.total_amount_usd,
                po.created_at
            FROM purchase_orders po
            JOIN suppliers s ON s.id = po.supplier_id
            WHERE po.po_status = 'PENDING_PROCUREMENT'
            ORDER BY po.created_at DESC
            """
        ).fetchall()

    supplier_directory: dict[str, dict[str, Any]] = {}
    for row in suppliers:
        supplier_id = str(row["supplier_id"])
        if supplier_id not in supplier_directory:
            supplier_directory[supplier_id] = {
                "supplier_id": supplier_id,
                "name": row["name"],
                "email": row["email"],
                "phone": row["phone"],
                "active_inventory_items": [],
            }
        if row["inventory_item_id"] is None:
            continue
        supplier_directory[supplier_id]["active_inventory_items"].append(
            {
                "inventory_item_id": row["inventory_item_id"],
                "clean_part_number": row["clean_part_number"],
                "condition": row["condition"],
                "quantity_available": row["quantity_available"],
                "unit_cost_usd": row["unit_cost_usd"],
                "lead_time_days": row["lead_time_days"],
                "last_updated_at": row["last_updated_at"],
            }
        )

    return {
        "suppliers": list(supplier_directory.values()),
        "pending_purchase_orders": [dict(row) for row in pending_pos],
    }
