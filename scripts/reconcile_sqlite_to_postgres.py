"""Reconcile a timestamped SQLite backup into PostgreSQL.

Default mode is a read-only dry run. Pass --apply only after reviewing the
selected backup and confirming DATABASE_URL points at the intended target.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.dialects.postgresql import insert

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
BACKUP_ROOT = Path(os.getenv("SQLITE_BACKUP_DIR", str(ROOT / "backups")))
FILES = {
    "operations": "operations.db",
    "supplier_email": "supplier_email.db",
}


def latest_backup() -> Path:
    candidates = sorted((path for path in BACKUP_ROOT.iterdir() if path.is_dir()), reverse=True) if BACKUP_ROOT.exists() else []
    for candidate in candidates:
        if all((candidate / name).exists() for name in FILES.values()):
            return candidate
    raise FileNotFoundError("No timestamped operations and supplier-email SQLite backup found.")


def read_table(database: Path, table: str) -> list[dict[str, Any]]:
    if not database.exists():
        return []
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        present = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        return [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')] if present else []


def decode_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def read_source(backup: Path) -> dict[str, list[dict[str, Any]]]:
    ops = backup / FILES["operations"]
    supplier = backup / FILES["supplier_email"]
    source = {
        "customers": read_table(ops, "customers"),
        "rfqs": read_table(ops, "rfqs"),
        "rfq_items": read_table(ops, "rfq_items"),
        "customer_quotes": read_table(ops, "customer_quotes"),
        "customer_quote_items": read_table(ops, "customer_quote_items"),
        "communications": read_table(ops, "communications"),
        "operations_state": read_table(ops, "operations_state"),
        "suppliers": read_table(supplier, "suppliers"),
        "supplier_parts": read_table(supplier, "supplier_parts"),
        "inbound_emails": read_table(supplier, "inbound_emails"),
        "communication_tasks": read_table(supplier, "communication_tasks"),
    }
    state_row = next((row for row in source["operations_state"] if row.get("state_key") == "current"), None)
    state = decode_json(state_row.get("payload"), {}) if state_row else {}
    source["snapshot_rfqs"] = list(state.get("rfqs", {}).values())
    source["snapshot_rfq_items"] = [row for rows in state.get("rfq_items", {}).values() for row in rows]
    source["snapshot_quotes"] = list(state.get("quotes", {}).values())
    source["snapshot_quote_items"] = [row for rows in state.get("quote_items", {}).values() for row in rows]
    source["snapshot_audit_logs"] = [row for rows in state.get("audit_logs", {}).values() for row in rows]
    source["snapshot_suppliers"] = list(state.get("suppliers", {}).values())
    source["snapshot_inventory"] = list(state.get("inventory", {}).values())
    source["snapshot_shipments"] = list(state.get("shipments", {}).values())
    source["snapshot_shipment_events"] = [row for rows in state.get("shipment_events", {}).values() for row in rows]
    return source


def _date(value: Any) -> Any:
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return value
    return value


def target_rows(source: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    customers: dict[str, dict[str, Any]] = {}
    for row in source["customers"]:
        customers[str(row["id"])] = {
            "id": str(row["id"]), "company_name": row.get("company_name") or "",
            "contact_name": row.get("contact_name"), "email": row.get("email") or "",
        }

    rfqs: dict[str, dict[str, Any]] = {}
    input_rfqs = source["rfqs"] + source["snapshot_rfqs"]
    for row in input_rfqs:
        rfq_id = str(row["id"])
        customer_email = row.get("customer_email") or "unknown@reconciled.invalid"
        customer_name = row.get("customer_name") or "Reconciled Customer"
        customer_id = row.get("customer_id") or f"CUS-{str(customer_email).lower()}"
        customers.setdefault(customer_id, {
            "id": customer_id, "company_name": customer_name, "contact_name": customer_name,
            "email": customer_email,
        })
        rfqs[rfq_id] = {
            "id": rfq_id, "customer_id": customer_id, "customer_email": customer_email,
            "customer_name": customer_name, "part_number": row.get("part_number"),
            "description": row.get("description") or str(row.get("raw_text") or "")[:500],
            "quantity": row.get("quantity") or 1, "condition_requested": row.get("condition_requested"),
            "certification_requested": row.get("certification_requested"), "destination": row.get("destination"),
            "raw_text": row.get("raw_text") or "", "status": row.get("status") or "Intake",
            "thread_id": row.get("thread_id"), "created_at": _date(row.get("created_at")),
            "updated_at": _date(row.get("updated_at")),
        }

    rfq_items_by_id = {str(row["id"]): row for row in source["rfq_items"] + source["snapshot_rfq_items"] if row.get("id")}
    rfq_items = []
    for row in rfq_items_by_id.values():
        part_number = row.get("part_number") or row.get("requested_part_number") or "UNKNOWN"
        details = {key: value for key, value in row.items() if key not in {"id", "rfq_id", "part_number", "requested_part_number", "quantity", "condition_preference"}}
        rfq_items.append({"id": str(row["id"]), "rfq_id": str(row["rfq_id"]), "part_number": part_number,
                          "quantity": int(row.get("quantity") or 1), "condition_code": row.get("condition_code") or row.get("condition_preference"), "details": details})

    quotes_by_id: dict[str, dict[str, Any]] = {}
    for row in source["customer_quotes"] + source["snapshot_quotes"]:
        quote_id = str(row["id"])
        quotes_by_id[quote_id] = {"id": quote_id, "rfq_id": str(row["rfq_id"]), "status": row.get("status") or "Draft",
                                  "total_amount": row.get("total_price", row.get("total_amount", 0)) or 0,
                                  "created_at": _date(row.get("created_at"))}

    quote_items_by_id: dict[str, dict[str, Any]] = {}
    for row in source["customer_quote_items"] + source["snapshot_quote_items"]:
        item_id = str(row["id"])
        quote_items_by_id[item_id] = {
            "id": item_id, "quote_id": str(row["quote_id"]),
            "part_number": row.get("part_number") or "UNKNOWN", "quantity": int(row.get("quantity") or 1),
            "unit_price": row.get("unit_price") or 0,
            "details": {key: value for key, value in row.items() if key not in {"id", "quote_id", "part_number", "quantity", "unit_price"}},
        }

    suppliers: dict[str, dict[str, Any]] = {}
    for row in source["suppliers"]:
        supplier_id = str(row["id"])
        suppliers[supplier_id] = {
            "id": supplier_id, "company_name": row.get("company_name") or "Unknown Supplier",
            "email": row.get("email"), "phone": row.get("phone"),
            "approval_status": row.get("approval_status") or "Pending",
            "itar_certified": bool(row.get("itar_certified", 0)), "source": row.get("source") or "legacy_sqlite",
        }

    supplier_parts_by_key: dict[str, dict[str, Any]] = {}
    supplier_by_email = {str(row.get("email") or "").lower(): row for row in suppliers.values()}
    for row in source["supplier_parts"]:
        email = str(row.get("supplier_email") or "").lower()
        supplier = suppliers.get(str(row.get("supplier_id") or "")) or supplier_by_email.get(email)
        if not supplier:
            supplier_id = str(row.get("supplier_id") or f"SUP-{uuid.uuid5(uuid.NAMESPACE_URL, str(row.get('id') or '')).hex[:16].upper()}")[:64]
            supplier = {"id": supplier_id, "company_name": row.get("supplier_name") or "Unknown Supplier",
                        "email": row.get("supplier_email"), "phone": None, "approval_status": row.get("approval_status") or "Pending",
                        "itar_certified": False, "source": "legacy_sqlite"}
            suppliers[supplier_id] = supplier
            if email:
                supplier_by_email[email] = supplier
        source_id = row.get("source_email_id")
        stable_source = str(source_id or row.get("id") or "")
        offer_id = f"SPO-{uuid.uuid5(uuid.NAMESPACE_URL, stable_source).hex[:24].upper()}"
        supplier_parts_by_key[offer_id] = {
            "id": offer_id, "supplier_id": supplier["id"], "part_number": str(row.get("part_number") or "UNKNOWN").upper(),
            "condition_code": row.get("condition_code"), "description": row.get("description"),
            "quantity_available": row.get("quantity_available"), "unit_cost": row.get("unit_cost"),
            "currency": row.get("currency") or "USD", "certificate_type": row.get("certificate_type"),
            "lead_time_days": row.get("lead_time_days"), "availability_location": row.get("availability_location"),
            "warranty_terms": row.get("warranty_terms"),
            "trace_documents": row.get("trace_documents") if isinstance(row.get("trace_documents"), str) else json.dumps(row.get("trace_documents") or []),
            "source_email_id": source_id, "confidence": row.get("confidence"),
            "approval_status": row.get("approval_status") or "Pending",
        }

    audits = []
    for index, row in enumerate(source["snapshot_audit_logs"], start=1):
        audit_identity = f"{row.get('rfq_id', 'unknown')}:{row.get('id', '')}:{index}"
        audit_id = f"AUD-{uuid.uuid5(uuid.NAMESPACE_URL, audit_identity).hex[:32].upper()}"
        audits.append({"id": audit_id, "entity_id": str(row.get("rfq_id") or "unknown"),
                       "actor": str(row.get("agent_name") or "legacy_sqlite")[:128],
                       "action": str(row.get("action_type") or "reconciled")[:128],
                       "status": str(row.get("status") or "SUCCESS")[:32],
                       "payload": {"legacy_audit_id": row.get("id"), "message": row.get("message"), "payload_json": row.get("payload_json")},
                       "created_at": _date(row.get("timestamp"))})

    communications_by_id = {}
    for row in source["communications"]:
        comm_id = str(row.get("id") or "")
        if comm_id:
            communications_by_id[comm_id] = {
                "id": comm_id, "entity_type": row.get("entity_type") or "email",
                "entity_id": str(row.get("entity_id") or "unknown"),
                "recipient": row.get("recipient") or "unknown@example.invalid",
                "sender": row.get("sender") or "unknown@example.invalid", "channel": row.get("channel") or "email",
                "subject": row.get("subject") or "", "message": row.get("message") or "",
                "message_type": row.get("message_type"), "status": row.get("status") or "UNKNOWN",
                "sent_at": _date(row.get("sent_at")), "response_received": row.get("response_received"),
                "created_at": _date(row.get("created_at")),
            }

    inbound_emails = []
    for row in source["inbound_emails"]:
        if row.get("message_id"):
            inbound_emails.append({
                "id": str(row.get("id") or f"EML-{uuid.uuid5(uuid.NAMESPACE_URL, str(row['message_id'])).hex[:16].upper()}"),
                "mailbox": row.get("mailbox") or "purchasing", "message_id": str(row["message_id"]),
                "sender": row.get("sender"), "subject": row.get("subject"), "body": row.get("body") or "",
                "received_at": _date(row.get("received_at")),
                "processing_status": row.get("processing_status") or "processed",
                "extraction_error": row.get("extraction_error"),
            })

    tasks = []
    for row in source["communication_tasks"]:
        if row.get("id") and row.get("task_key"):
            tasks.append({
                "id": str(row["id"]), "task_key": str(row["task_key"]),
                "recipient": row.get("recipient") or "unknown@example.invalid",
                "subject": row.get("subject") or "", "body": row.get("body") or "",
                "task_type": row.get("task_type") or "email", "mailbox": row.get("mailbox") or "sales",
                "reply_to": row.get("reply_to"), "status": row.get("status") or "pending",
                "attempts": int(row.get("attempts") or 0), "max_attempts": int(row.get("max_attempts") or 5),
                "last_error": row.get("last_error"), "due_at": _date(row.get("due_at")),
                "created_at": _date(row.get("created_at")), "sent_at": _date(row.get("sent_at")),
            })

    operational_records: dict[tuple[str, str], dict[str, Any]] = {}

    def put_operational(domain: str, record_id: Any, payload: dict[str, Any]) -> None:
        if record_id:
            operational_records[(domain, str(record_id))] = {"domain": domain, "record_id": str(record_id), "payload": payload}

    for domain, domain_rows in (
        ("rfqs", source["snapshot_rfqs"]),
        ("rfq_items", source["snapshot_rfq_items"]),
        ("quotes", source["snapshot_quotes"]),
        ("quote_items", source["snapshot_quote_items"]),
        ("suppliers", source["snapshot_suppliers"]),
        ("inventory", source["snapshot_inventory"]),
        ("shipments", source["snapshot_shipments"]),
        ("shipment_events", source["snapshot_shipment_events"]),
    ):
        for row in domain_rows:
            record_id = str(row.get("id") or "")
            if record_id:
                put_operational(domain, record_id, row)

    snapshot_rfqs_by_id = {str(row.get("id")): row for row in source["snapshot_rfqs"] if row.get("id")}
    for row in rfqs.values():
        record = dict(snapshot_rfqs_by_id.get(row["id"], {}))
        record.update({
            "id": row["id"], "customer_name": row["customer_name"],
            "customer_email": row["customer_email"], "status": row["status"],
            "raw_text": row["raw_text"], "thread_id": row["thread_id"],
        })
        if "created_at" not in record and row.get("created_at") is not None:
            record["created_at"] = row["created_at"]
        record.setdefault("workflow_state", row["status"])
        record.setdefault("version", 1)
        record.setdefault("automation_paused", False)
        record.setdefault("pause_reason", None)
        put_operational("rfqs", row["id"], record)

    snapshot_rfq_items_by_id = {str(row.get("id")): row for row in source["snapshot_rfq_items"] if row.get("id")}
    for row in rfq_items:
        record = dict(snapshot_rfq_items_by_id.get(row["id"], {}))
        record.update({
            "id": row["id"], "rfq_id": row["rfq_id"],
            "requested_part_number": row["part_number"],
            "resolved_part_number": record.get("resolved_part_number"),
            "quantity": row["quantity"], "condition_preference": row["condition_code"] or "NE",
        })
        record.setdefault("uom", row.get("details", {}).get("uom", "EA"))
        record.setdefault("aircraft_type", row.get("details", {}).get("aircraft_type"))
        put_operational("rfq_items", row["id"], record)

    snapshot_quotes_by_id = {str(row.get("id")): row for row in source["snapshot_quotes"] if row.get("id")}
    for row in quotes_by_id.values():
        record = dict(snapshot_quotes_by_id.get(row["id"], {}))
        record.update({"id": row["id"], "rfq_id": row["rfq_id"], "status": row["status"], "total_amount": row["total_amount"]})
        record.setdefault("subtotal", row["total_amount"])
        record.setdefault("shipping_cost", 0.0)
        record.setdefault("version", 1)
        put_operational("quotes", row["id"], record)

    snapshot_quote_items_by_id = {str(row.get("id")): row for row in source["snapshot_quote_items"] if row.get("id")}
    for row in quote_items_by_id.values():
        details = row.get("details") or {}
        record = dict(snapshot_quote_items_by_id.get(row["id"], {}))
        record.update({
            "id": row["id"], "quote_id": row["quote_id"], "rfq_item_id": details.get("rfq_item_id", ""),
            "part_number": row["part_number"], "description": details.get("description") or row["part_number"],
            "quantity": row["quantity"], "uom": details.get("uom", "EA"),
            "unit_price": row["unit_price"], "source": details.get("source", "Legacy"),
            "unit_cost": details.get("unit_cost", 0.0), "margin_percent": details.get("margin_percent", 0.0),
            "certificate_type": details.get("certification") or details.get("certificate_type") or "Unavailable",
            "condition": details.get("condition"), "lead_time_days": details.get("lead_time"),
            "compliance_status": details.get("compliance_status", "Needs_Review"),
        })
        attachments = details.get("attachments", [])
        record["attachments"] = decode_json(attachments, []) if isinstance(attachments, str) else attachments
        put_operational("quote_items", row["id"], record)

    snapshot_suppliers_by_id = {str(row.get("id")): row for row in source["snapshot_suppliers"] if row.get("id")}
    for row in suppliers.values():
        supplier_id = row["id"]
        record = dict(snapshot_suppliers_by_id.get(supplier_id, {}))
        if not record:
            company = row.get("company_name") or "Unknown Supplier"
            record = {
                "id": supplier_id, "company_name": company, "dba_name": None,
                "contact_name": row.get("contact_name") or company, "contact_title": None,
                "phone": row.get("phone") or "", "phone_alt": None,
                "email": row.get("email") or "", "email_quotes": None, "website": None,
                "address_line1": "", "address_line2": None, "city": "",
                "state_province": "", "postal_code": "", "country": "",
                "approval_status": row.get("approval_status") or "Pending",
                "itar_certified": bool(row.get("itar_certified")), "account_manager": None, "notes": None,
            }
        put_operational("suppliers", supplier_id, record)

    for index, row in enumerate(source["snapshot_audit_logs"], start=1):
        record_id = f"{row.get('rfq_id', 'unknown')}:{row.get('id') or index}"
        put_operational("audit_logs", record_id, row)

    records = list(operational_records.values())

    return {
        "customers": list(customers.values()), "rfqs": list(rfqs.values()), "rfq_items": rfq_items,
        "quotes": list(quotes_by_id.values()), "quote_items": list(quote_items_by_id.values()),
        "suppliers": list(suppliers.values()), "supplier_parts": list(supplier_parts_by_key.values()),
        "audit_events": audits, "communications": list(communications_by_id.values()),
        "inbound_emails": inbound_emails, "communication_tasks": tasks,
        "operational_records": records,
    }


def reconciliation_warnings(source: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    full_quote_item_ids = {str(row.get("id")) for row in source["snapshot_quote_items"] if row.get("id")}
    incomplete_quote_items = [
        row for row in source["customer_quote_items"]
        if str(row.get("id")) not in full_quote_item_ids
    ]
    if incomplete_quote_items:
        warnings.append({
            "severity": "blocking",
            "table": "customer_quote_items",
            "count": len(incomplete_quote_items),
            "reason": "SQLite normalized quote rows do not contain source, acquisition cost, margin, or compliance fields required to recreate QuoteItem runtime payloads. Recover a current complete state export or reconcile these records under an explicit manual-review policy before apply.",
        })

    complete_supplier_ids = {str(row.get("id")) for row in source["snapshot_suppliers"] if row.get("id")}
    incomplete_suppliers = [row for row in source["suppliers"] if str(row.get("id")) not in complete_supplier_ids]
    if incomplete_suppliers:
        warnings.append({
            "severity": "review", "table": "suppliers", "count": len(incomplete_suppliers),
            "reason": "Supplier registry rows do not carry the full supplier contact/address profile required by the legacy Supplier model; reconcile missing profile fields before enabling profile-dependent actions.",
        })
    return warnings


def assert_apply_has_complete_source(warnings: list[dict[str, Any]]) -> None:
    blockers = [warning for warning in warnings if warning["severity"] == "blocking"]
    if blockers:
        raise RuntimeError(
            "Reconciliation apply is blocked by incomplete source data: "
            + "; ".join(f"{item['table']}={item['count']}" for item in blockers)
        )


def preflight_database(url: str, attempts: int = 5) -> None:
    engine = create_engine(url, pool_pre_ping=True)
    delay = 0.5
    try:
        for attempt in range(max(1, attempts)):
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                return
            except Exception as exc:
                if attempt + 1 >= attempts:
                    raise RuntimeError(f"Target PostgreSQL is unreachable ({type(exc).__name__}).") from exc
                time.sleep(delay)
                delay = min(delay * 2, 8)
    finally:
        engine.dispose()


def upsert_rows(connection, metadata: MetaData, table_name: str, rows: list[dict[str, Any]], apply: bool) -> tuple[int, int]:
    if not rows:
        return 0, 0
    table = metadata.tables.get(table_name) or Table(table_name, metadata, autoload_with=connection)
    allowed = {column.name for column in table.columns}
    filtered = [{key: value for key, value in row.items() if key in allowed} for row in rows]
    primary_keys = [column.name for column in table.primary_key.columns]
    if not primary_keys:
        raise RuntimeError(f"Target table {table_name} has no primary key; refusing reconciliation.")
    if not apply:
        return len(filtered), len(filtered)
    for start in range(0, len(filtered), 250):
        statement = insert(table).values(filtered[start:start + 250])
        statement = statement.on_conflict_do_nothing(index_elements=primary_keys)
        connection.execute(statement)
    return len(filtered), len(filtered)


def reconcile(backup: Path, *, apply: bool, url: str | None) -> dict[str, Any]:
    source = read_source(backup)
    rows = target_rows(source)
    warnings = reconciliation_warnings(source)
    summary: dict[str, Any] = {
        "backup": str(backup), "mode": "apply" if apply else "dry-run",
        "tables": {}, "warnings": warnings,
    }
    if apply:
        assert_apply_has_complete_source(warnings)
    if not url:
        raise RuntimeError("DATABASE_URL is required for reconciliation. No local fallback is inferred.")
    preflight_database(url)
    engine = create_engine(url, pool_pre_ping=True)
    try:
        metadata = MetaData()
        with engine.begin() as connection:
            existing = set(inspect(connection).get_table_names())
            for table_name, records in rows.items():
                if table_name not in existing:
                    raise RuntimeError(f"Target PostgreSQL table is missing: {table_name}. Apply reviewed migrations first.")
                source_count, _ = upsert_rows(connection, metadata, table_name, records, apply)
                summary["tables"][table_name] = {"source_keys": source_count, "status": "upserted" if apply else "would_upsert"}
            if apply:
                for table_name, records in rows.items():
                    table = metadata.tables.get(table_name) or Table(table_name, metadata, autoload_with=connection)
                    pk = [column.name for column in table.primary_key.columns]
                    if records:
                        keys = [tuple(row[name] for name in pk) for row in records]
                        if len(pk) == 1:
                            found = set(connection.execute(select(table.c[pk[0]]).where(table.c[pk[0]].in_([key[0] for key in keys]))).scalars())
                            missing = sorted({key[0] for key in keys} - found)
                        else:
                            stmt = select(*[table.c[name] for name in pk])
                            found = {tuple(key) for key in connection.execute(stmt).all()}
                            missing = sorted(set(keys) - found)
                        if missing:
                            raise RuntimeError(f"Post-reconciliation parity failed for {table_name}: {len(missing)} source keys missing")
                summary["parity"] = "passed"
            else:
                connection.rollback()
    finally:
        engine.dispose()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", type=Path, default=None, help="Timestamped backup directory; defaults to newest local backup")
    parser.add_argument("--apply", action="store_true", help="Apply upserts. Without this option, runs a read-only dry run.")
    parser.add_argument("--plan-only", action="store_true", help="Print source row counts without requiring PostgreSQL connectivity.")
    args = parser.parse_args()
    try:
        backup = args.backup_dir or latest_backup()
        source = read_source(backup)
        mapped = target_rows(source)
        if args.plan_only:
            print(json.dumps({
                "backup": str(backup), "mode": "plan-only",
                "source_tables": {name: len(rows) for name, rows in mapped.items()},
                "warnings": reconciliation_warnings(source),
            }, indent=2))
            return 0
        url = os.getenv("DATABASE_URL", "").strip()
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        result = reconcile(backup, apply=args.apply, url=url or None)
        print(json.dumps(result, indent=2, default=str))
        return 0
    except Exception as exc:
        print(f"reconciliation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())