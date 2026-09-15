import argparse
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.relational_db import DEFAULT_DB_PATH, db_connection, ensure_schema, seed_relational_mock_data


def _clear_terminal() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _print_table(headers: list[str], rows: list[list[object]]) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(str(value)))

    format_line = " | ".join(f"{{:<{width}}}" for width in widths)
    divider = "-+-".join("-" * width for width in widths)
    print(format_line.format(*headers))
    print(divider)
    for row in rows:
        print(format_line.format(*[str(item) for item in row]))


def _render_snapshot(db_path: Path) -> None:
    ensure_schema(db_path)
    with db_connection(db_path) as connection:
        totals = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM suppliers) AS total_suppliers,
                (SELECT COUNT(DISTINCT clean_part_number) FROM inventory_items) AS total_unique_inventory_parts,
                (SELECT COUNT(*) FROM clients) AS total_clients,
                (SELECT COUNT(*) FROM client_rfqs WHERE status = 'PENDING_QUOTE') AS total_pending_rfqs,
                (SELECT COUNT(*) FROM purchase_orders WHERE po_status = 'PENDING_PROCUREMENT') AS total_pending_pos
            """
        ).fetchone()

        recent_inventory = connection.execute(
            """
            SELECT
                i.last_updated_at,
                i.clean_part_number,
                i.condition,
                i.quantity_available,
                i.unit_cost_usd,
                s.name AS supplier_name
            FROM inventory_items i
            JOIN suppliers s ON s.id = i.supplier_id
            ORDER BY i.last_updated_at DESC
            LIMIT 10
            """
        ).fetchall()

        pipeline = connection.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM client_rfqs
            WHERE status IN ('PO_PENDING', 'SOLVED', 'PENDING_QUOTE')
            GROUP BY status
            ORDER BY status
            """
        ).fetchall()

    print("Database summary")
    print("----------------")
    print(f"Total Suppliers: {totals['total_suppliers']}")
    print(f"Total Unique Inventory Parts: {totals['total_unique_inventory_parts']}")
    print(f"Total Clients: {totals['total_clients']}")
    print(f"Total Pending RFQs: {totals['total_pending_rfqs']}")
    print(f"Total Pending POs: {totals['total_pending_pos']}")
    print()

    print("Top 10 recently updated inventory items")
    _print_table(
        ["Updated At", "Part", "Cond", "Qty", "Unit Cost USD", "Supplier"],
        [
            [
                row["last_updated_at"],
                row["clean_part_number"],
                row["condition"],
                row["quantity_available"],
                row["unit_cost_usd"],
                row["supplier_name"],
            ]
            for row in recent_inventory
        ],
    )
    print()

    print("Client RFQ pipeline")
    _print_table(
        ["Status", "Count"],
        [[row["status"], row["count"]] for row in pipeline],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect relational SQLite database state.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    parser.add_argument("--watch", action="store_true", help="Refresh every 5 seconds until interrupted.")
    parser.add_argument("--seed-if-empty", action="store_true", help="Seed mock relational data before displaying.")
    args = parser.parse_args()

    db_path = Path(args.db)
    if args.seed_if_empty:
        seed_relational_mock_data(db_path)
    else:
        ensure_schema(db_path)

    while True:
        if args.watch:
            _clear_terminal()
        _render_snapshot(db_path)
        if not args.watch:
            break
        time.sleep(5)


if __name__ == "__main__":
    main()
