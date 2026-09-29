"""Reconcile a timestamped SQLite backup into PostgreSQL.

Default mode is a read-only dry run. Pass --apply only after reviewing the
selected backup and confirming DATABASE_URL points at the intended target.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parents[1]
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


def _line_item_signature(row: dict[str, Any]) -> str:
    fields = (
        "quote_id", "rfq_item_id", "part_number", "description", "quantity",
        "condition", "certification", "unit_price", "lead_time", "attachments",
    )
    details = row.get("details") if isinstance(row.get("details"), dict) else row
    signature = {key: row.get(key) for key in fields}
    for key in ("source", "unit_cost", "margin_percent", "certificate_type", "compliance_status"):
        if key in row or key in details:
            signature[f"detail:{key}"] = details.get(key, row.get(key))
    return json.dumps(signature, sort_keys=True, default=str)


def _quarantine_id(prefix: str, source_id: Any, row: dict[str, Any]) -> str:
    identity = str(source_id or json.dumps(row, sort_keys=True, default=str))
    return f"{prefix}-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32].upper()}"


def _tax_id(value: Any) -> str:
    return "".join(character for character in str(value or "").upper() if character.isalnum())


def _email_domain(value: Any) -> str:
    email = str(value or "").strip().lower()
    if "@" not in email:
        return ""
    domain = email.rsplit("@", 1)[1].strip().rstrip(".")
    if domain in {
        "gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com",
        "live.com", "icloud.com", "aol.com", "proton.me", "protonmail.com",
    }:
        return ""
    return domain


def match_supplier_ids(
    source_suppliers: list[dict[str, Any]], target_suppliers: list[dict[str, Any]],
) -> tuple[dict[str, str], set[str]]:
    """Match source IDs only to unique tax-ID or corporate-domain identities."""
    target_by_tax: dict[str, set[str]] = {}
    target_by_domain: dict[str, set[str]] = {}
    for target in target_suppliers:
        target_id = str(target.get("id") or "")
        tax_id = _tax_id(target.get("tax_id"))
        domain = _email_domain(target.get("email"))
        if target_id and tax_id:
            target_by_tax.setdefault(tax_id, set()).add(target_id)
        if target_id and domain:
            target_by_domain.setdefault(domain, set()).add(target_id)

    matches: dict[str, str] = {}
    ambiguous: set[str] = set()
    for source in source_suppliers:
        source_id = str(source.get("id") or "")
        tax_id = _tax_id(source.get("tax_id"))
        domain = _email_domain(source.get("email"))
        candidates = target_by_tax.get(tax_id, set()) if tax_id else set()
        if len(candidates) == 1:
            matches[source_id] = next(iter(candidates))
        elif len(candidates) > 1:
            ambiguous.add(source_id)
            continue
        elif domain:
            candidates = target_by_domain.get(domain, set())
            if len(candidates) == 1:
                matches[source_id] = next(iter(candidates))
            elif len(candidates) > 1:
                ambiguous.add(source_id)
    return matches, ambiguous


def target_rows(
    source: dict[str, list[dict[str, Any]]],
    target_suppliers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
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

    snapshot_quote_item_ids = {str(row.get("id")) for row in source["snapshot_quote_items"] if row.get("id")}
    source_quote_rows = source["customer_quotes"] + source["snapshot_quotes"]
    source_quote_by_id = {str(row.get("id")): row for row in source_quote_rows if row.get("id")}
    valid_rfq_ids = set(rfqs)
    accepted_quote_item_rows: list[tuple[dict[str, Any], bool]] = []
    quarantine_quote_items: list[dict[str, Any]] = []
    line_item_signatures: set[str] = set()
    skipped_duplicate_line_items = 0
    # Prefer complete operational snapshots over normalized legacy rows.
    for row, is_snapshot in [
        *((row, True) for row in source["snapshot_quote_items"]),
        *((row, False) for row in source["customer_quote_items"]),
    ]:
        signature = _line_item_signature(row)
        if signature in line_item_signatures:
            skipped_duplicate_line_items += 1
            continue
        line_item_signatures.add(signature)
        quote_id = str(row.get("quote_id") or "")
        parent_quote = source_quote_by_id.get(quote_id)
        rfq_id = str(row.get("rfq_id") or (parent_quote or {}).get("rfq_id") or "")
        if not parent_quote or not rfq_id or rfq_id not in valid_rfq_ids:
            item_id = str(row.get("id") or _quarantine_id("QI", None, row))
            quarantine_quote_items.append({
                "id": _quarantine_id("QQI", item_id, row), "source_id": item_id,
                "quote_id": quote_id or None, "rfq_id": rfq_id or None,
                "payload": row,
                "reason": "Quote item has no valid parent RFQ and is excluded from operational quote items.",
                "is_active": False,
            })
            continue
        accepted_quote_item_rows.append((row, is_snapshot))

    accepted_customer_quote_items = [
        row for row, is_snapshot in accepted_quote_item_rows if not is_snapshot
    ]
    incomplete_quote_items = [
        row for row, _is_snapshot in accepted_quote_item_rows
        if str(row.get("id") or "") not in snapshot_quote_item_ids
    ]
    incomplete_quote_ids = {str(row.get("quote_id")) for row in incomplete_quote_items if row.get("quote_id")}

    quotes_by_id: dict[str, dict[str, Any]] = {}
    for row in source_quote_rows:
        quote_id = str(row["id"])
        original_status = row.get("status") or "Draft"
        quote_status = "Pending_Internal_Review" if quote_id in incomplete_quote_ids else original_status
        quotes_by_id[quote_id] = {"id": quote_id, "rfq_id": str(row["rfq_id"]), "status": quote_status,
                                  "total_amount": row.get("total_price", row.get("total_amount", 0)) or 0,
                                  "created_at": _date(row.get("created_at")),
                                  "reconciliation_original_status": original_status if quote_id in incomplete_quote_ids else None}
    incomplete_rfq_ids = {quotes_by_id[quote_id]["rfq_id"] for quote_id in incomplete_quote_ids if quote_id in quotes_by_id}
    for rfq_id in incomplete_rfq_ids:
        if rfq_id in rfqs:
            rfqs[rfq_id]["reconciliation_original_status"] = rfqs[rfq_id]["status"]
            rfqs[rfq_id]["status"] = "Pending_Internal_Review"
            rfqs[rfq_id]["automation_paused"] = True
            rfqs[rfq_id]["pause_reason"] = "Legacy quote items require operator review."

    customer_quotes_by_id: dict[str, dict[str, Any]] = {}
    for row in source_quote_rows:
        quote_id = str(row["id"])
        item_rows = [item for item in source["customer_quote_items"] if str(item.get("quote_id")) == quote_id]
        first_item = item_rows[0] if item_rows else {}
        customer_quotes_by_id[quote_id] = {
            "id": quote_id, "rfq_id": str(row["rfq_id"]),
            "quote_number": row.get("quote_number") or quote_id,
            "unit_price": row.get("unit_price") if row.get("unit_price") is not None else (first_item.get("unit_price") or 0),
            "quantity": int(row.get("quantity") or first_item.get("quantity") or 1),
            "total_price": row.get("total_price", row.get("total_amount", 0)) or 0,
            "currency": row.get("currency") or "USD", "lead_time": row.get("lead_time", row.get("lead_time_days")),
            "condition": row.get("condition"), "certification": row.get("certification"),
            "valid_until": row.get("valid_until"),
            "status": quotes_by_id[quote_id]["status"],
            "created_at": _date(row.get("created_at")), "updated_at": _date(row.get("updated_at")),
        }

    customer_quote_items_by_id: dict[str, dict[str, Any]] = {}
    for row in accepted_customer_quote_items:
        item_id = str(row["id"])
        attachments = row.get("attachments") or ""
        customer_quote_items_by_id[item_id] = {
            "id": item_id, "quote_id": str(row["quote_id"]), "rfq_item_id": row.get("rfq_item_id"),
            "part_number": row.get("part_number") or "UNKNOWN", "description": row.get("description"),
            "quantity": int(row.get("quantity") or 1), "condition": row.get("condition"),
            "certification": row.get("certification") or "PENDING_OPERATOR_REVIEW", "unit_price": row.get("unit_price") or 0,
            "lead_time": row.get("lead_time"),
            "attachments": attachments if isinstance(attachments, str) else json.dumps(attachments),
            "created_at": _date(row.get("created_at")), "updated_at": _date(row.get("updated_at")),
        }

    quote_items_by_id: dict[str, dict[str, Any]] = {}
    for row, _is_snapshot in accepted_quote_item_rows:
        item_id = str(row.get("id") or _quarantine_id("QI", None, row))
        quote_items_by_id[item_id] = {
            "id": item_id, "quote_id": str(row["quote_id"]),
            "part_number": row.get("part_number") or "UNKNOWN", "quantity": int(row.get("quantity") or 1),
            "unit_price": row.get("unit_price") or 0,
            "details": row.get("details") if isinstance(row.get("details"), dict) else {
                key: value for key, value in row.items()
                if key not in {"id", "quote_id", "part_number", "quantity", "unit_price"}
            },
        }

    review_records: dict[str, dict[str, Any]] = {}

    def add_review(review_key: str, *, entity_id: str | None, source_payload: dict[str, Any], reason: str, hold_flags: list[str]) -> None:
        review_id = f"REV-{uuid.uuid5(uuid.NAMESPACE_URL, review_key).hex[:16].upper()}"
        created_at = _date(source_payload.get("created_at")) or datetime.now(timezone.utc)
        review_records[review_key] = {
            "id": review_id, "idempotency_key": review_key[:255],
            "task": "sqlite_reconciliation_review", "prompt_version": "sqlite-reconcile-v1",
            "entity_id": entity_id,
            "source_text": json.dumps(source_payload, default=str, ensure_ascii=False),
            "extraction_json": json.dumps(source_payload, default=str, ensure_ascii=False),
            "reason": reason, "hold_flags_json": json.dumps(hold_flags), "status": "PENDING",
            "created_at": created_at, "updated_at": created_at,
        }

    for row in incomplete_quote_items:
        item_id = str(row.get("id") or "unknown")
        add_review(
            f"sqlite-reconcile:quote-item:{item_id}", entity_id=str(row.get("quote_id") or "") or None,
            source_payload=row,
            reason="Legacy normalized quote item lacks source, acquisition cost, margin, or compliance fields needed for safe reuse.",
            hold_flags=["source", "unit_cost", "margin_percent", "compliance_status"],
        )

    source_supplier_profiles: dict[str, dict[str, Any]] = {}
    for row in source["suppliers"]:
        if row.get("id"):
            source_supplier_profiles[str(row["id"])] = dict(row)
    for row in source["snapshot_suppliers"]:
        if row.get("id"):
            source_supplier_profiles.setdefault(str(row["id"]), {}).update(row)
    for offer in source["supplier_parts"]:
        source_id = str(offer.get("supplier_id") or f"SUP-{hashlib.sha256(str(offer.get('supplier_email') or offer.get('id') or '').encode('utf-8')).hexdigest()[:24].upper()}")
        if source_id and source_id not in source_supplier_profiles:
            source_supplier_profiles[source_id] = {
                "id": source_id, "company_name": offer.get("supplier_name") or "Unknown Supplier",
                "email": offer.get("supplier_email"),
            }

    full_supplier_profile_ids = {str(row.get("id")) for row in source["snapshot_suppliers"] if row.get("id")}
    source_profile_rows = list(source_supplier_profiles.values())
    supplier_matches, ambiguous_supplier_ids = match_supplier_ids(source_profile_rows, target_suppliers or [])
    supplier_target_ids: dict[str, str | None] = {}
    suppliers: dict[str, dict[str, Any]] = {}
    suppliers_requiring_review: set[str] = set()
    quarantine_supplier_profiles: dict[str, dict[str, Any]] = {}
    supplier_by_email: dict[str, str] = {}
    source_supplier_parts: dict[str, list[dict[str, Any]]] = {}
    for row in source["supplier_parts"]:
        source_supplier_id = str(row.get("supplier_id") or "")
        if source_supplier_id:
            source_supplier_parts.setdefault(source_supplier_id, []).append(row)

    for source_id, row in source_supplier_profiles.items():
        target_id = supplier_matches.get(source_id)
        is_complete = source_id in full_supplier_profile_ids
        supplier_target_ids[source_id] = target_id or (source_id if is_complete else None)
        email = str(row.get("email") or "").strip().lower()
        if email:
            supplier_by_email[email] = supplier_target_ids[source_id] or ""
        if target_id and is_complete:
            continue
        if is_complete:
            suppliers[source_id] = {
                "id": source_id, "company_name": row.get("company_name") or "Unknown Supplier",
                "email": row.get("email"), "phone": row.get("phone"),
                "approval_status": row.get("approval_status") or "Pending",
                "itar_certified": bool(row.get("itar_certified", 0)),
                "source": row.get("source") or "legacy_sqlite",
            }
            continue

        suppliers_requiring_review.add(source_id)
        related_parts = source_supplier_parts.get(source_id, [])
        reason = (
            "Supplier identity matches a live supplier; the incomplete source profile is quarantined and the live supplier record is not updated."
            if source_id in supplier_matches
            else "Supplier profile is incomplete or its target identity is ambiguous; it is staged inactive for operator review."
        )
        quarantine_supplier_profiles[source_id] = {
            "id": _quarantine_id("QSP", source_id, row), "source_id": source_id,
            "matched_supplier_id": target_id,
            "payload": {**row, "related_supplier_parts": related_parts},
            "reason": reason, "is_active": False,
        }
        add_review(
            f"sqlite-reconcile:supplier:{source_id}", entity_id=source_id, source_payload=row,
            reason=reason,
            hold_flags=["contact_name", "phone", "address_line1", "city", "state_province", "postal_code"],
        )

    supplier_parts_by_key: dict[str, dict[str, Any]] = {}
    quarantined_offer_count = 0
    for row in source["supplier_parts"]:
        source_supplier_id = str(row.get("supplier_id") or "")
        email = str(row.get("supplier_email") or "").strip().lower()
        supplier_id = supplier_target_ids.get(source_supplier_id) if source_supplier_id else supplier_by_email.get(email)
        if not supplier_id:
            quarantined_offer_count += 1
            continue
        source_id = row.get("source_email_id")
        stable_source = str(source_id or row.get("id") or "")
        offer_id = f"SPO-{uuid.uuid5(uuid.NAMESPACE_URL, stable_source).hex[:24].upper()}"
        supplier_parts_by_key[offer_id] = {
            "id": offer_id, "supplier_id": supplier_id, "part_number": str(row.get("part_number") or "UNKNOWN").upper(),
            "condition_code": row.get("condition_code"), "description": row.get("description"),
            "quantity_available": row.get("quantity_available"), "unit_cost": row.get("unit_cost"),
            "currency": row.get("currency") or "USD", "certificate_type": row.get("certificate_type"),
            "lead_time_days": row.get("lead_time_days"), "availability_location": row.get("availability_location"),
            "warranty_terms": row.get("warranty_terms"),
            "trace_documents": row.get("trace_documents") if isinstance(row.get("trace_documents"), str) else json.dumps(row.get("trace_documents") or []),
            "source_email_id": source_id, "confidence": row.get("confidence"),
            "approval_status": "Pending_Internal_Review" if source_supplier_id in suppliers_requiring_review else row.get("approval_status") or "Pending",
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
        if row["id"] in incomplete_rfq_ids:
            record["reconciliation_original_status"] = row.get("reconciliation_original_status")
            record["status"] = "Pending_Internal_Review"
        if "created_at" not in record and row.get("created_at") is not None:
            record["created_at"] = row["created_at"]
        record.setdefault("workflow_state", row["status"])
        record.setdefault("version", 1)
        if row["id"] in incomplete_rfq_ids:
            record["automation_paused"] = True
            record["pause_reason"] = "Legacy quote items require operator review."
        else:
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
        original_status = record.get("status") or row.get("reconciliation_original_status")
        record.update({"id": row["id"], "rfq_id": row["rfq_id"], "status": row["status"], "total_amount": row["total_amount"]})
        if row["status"] == "Pending_Internal_Review":
            record["reconciliation_original_status"] = original_status
        record.setdefault("subtotal", row["total_amount"])
        record.setdefault("shipping_cost", 0.0)
        record.setdefault("version", 1)
        put_operational("quotes", row["id"], record)

    snapshot_quote_items_by_id = {str(row.get("id")): row for row in source["snapshot_quote_items"] if row.get("id")}
    for row in quote_items_by_id.values():
        is_incomplete = row["id"] not in snapshot_quote_items_by_id
        details = row.get("details") or {}
        record = dict(snapshot_quote_items_by_id.get(row["id"], {}))
        record.update({
            "id": row["id"], "quote_id": row["quote_id"], "rfq_item_id": details.get("rfq_item_id", ""),
            "part_number": row["part_number"], "description": details.get("description") or row["part_number"],
            "quantity": row["quantity"], "uom": details.get("uom") or "EA",
            "unit_price": row["unit_price"], "source": details.get("source") or "Legacy",
            "unit_cost": details.get("unit_cost") if details.get("unit_cost") is not None else 0.0,
            "margin_percent": details.get("margin_percent") if details.get("margin_percent") is not None else 0.0,
            "certificate_type": details.get("certification") or details.get("certificate_type") or "Unavailable",
            "condition": details.get("condition"), "lead_time_days": details.get("lead_time"),
            "compliance_status": details.get("compliance_status") or "Needs_Review",
        })
        attachments = details.get("attachments", [])
        record["attachments"] = decode_json(attachments, []) if isinstance(attachments, str) else attachments
        if is_incomplete:
            record["reconciliation_review_required"] = True
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
        "customer_quotes": list(customer_quotes_by_id.values()),
        "customer_quote_items": list(customer_quote_items_by_id.values()),
        "suppliers": list(suppliers.values()), "supplier_parts": list(supplier_parts_by_key.values()),
        "audit_events": audits, "communications": list(communications_by_id.values()),
        "inbound_emails": inbound_emails, "communication_tasks": tasks,
        "operator_review_queue": list(review_records.values()), "operational_records": records,
        "quarantine_quote_items": quarantine_quote_items,
        "quarantine_supplier_profiles": list(quarantine_supplier_profiles.values()),
        "_reconciliation": {
            "skipped_duplicate_line_items": skipped_duplicate_line_items,
            "quarantined_quote_items": len(quarantine_quote_items),
            "quarantined_supplier_profiles": len(quarantine_supplier_profiles),
            "quarantined_supplier_offers": quarantined_offer_count,
            "ambiguous_supplier_matches": len(ambiguous_supplier_ids),
        },
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
            "severity": "review",
            "table": "customer_quote_items",
            "count": len(incomplete_quote_items),
            "reason": "SQLite normalized quote rows lack source, acquisition cost, margin, or compliance fields. Valid-parent lines receive conservative defaults and a review hold; orphan lines are staged inactive in quarantine.",
        })

    complete_supplier_ids = {str(row.get("id")) for row in source["snapshot_suppliers"] if row.get("id")}
    incomplete_suppliers = [row for row in source["suppliers"] if str(row.get("id")) not in complete_supplier_ids]
    if incomplete_suppliers:
        warnings.append({
            "severity": "review", "table": "suppliers", "count": len(incomplete_suppliers),
            "reason": "Supplier registry rows lack a complete contact/address profile. Unmatched profiles are staged inactive in quarantine; matched live suppliers are not overwritten and related offer foreign keys map to the live ID.",
        })
    return warnings


def assert_apply_has_complete_source(warnings: list[dict[str, Any]]) -> None:
    blockers = [warning for warning in warnings if warning["severity"] == "blocking"]
    if blockers:
        raise RuntimeError(
            "Reconciliation apply is blocked by incomplete source data: "
            + "; ".join(f"{item['table']}={item['count']}" for item in blockers)
        )


def assert_disposition_approval(warnings: list[dict[str, Any]], *, approved: bool, approval_reference: str) -> None:
    review_items = [warning for warning in warnings if warning["severity"] == "review"]
    if not review_items:
        return
    if not approved or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", approval_reference.strip()):
        raise RuntimeError(
            "Reconciliation apply requires --approve-disposition-policy and a sanitized --approval-reference."
        )


def assert_reconciliation_safe(*, target_key_collisions: int, schema_truncations: int, foreign_key_violations: int) -> None:
    failures = {
        "target_key_collisions": target_key_collisions,
        "schema_truncations": schema_truncations,
        "foreign_key_violations": foreign_key_violations,
    }
    blocking = {name: count for name, count in failures.items() if count > 0}
    if blocking:
        detail = ", ".join(f"{name}={count}" for name, count in blocking.items())
        raise RuntimeError(f"Reconciliation safety checks failed; transaction must roll back: {detail}")


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


def target_supplier_identities(connection, metadata: MetaData) -> list[dict[str, Any]]:
    suppliers_table = reflected_table(connection, metadata, "suppliers")
    result = connection.execute(select(suppliers_table)).mappings()
    identities = {str(row["id"]): dict(row) for row in result}
    operational_table = reflected_table(connection, metadata, "operational_records")
    profile_rows = connection.execute(
        select(operational_table.c.record_id, operational_table.c.payload)
        .where(operational_table.c.domain == "suppliers")
    ).mappings()
    for row in profile_rows:
        profile = decode_json(row["payload"], {})
        target = identities.setdefault(str(row["record_id"]), {"id": str(row["record_id"])})
        target["tax_id"] = profile.get("tax_id") or profile.get("tax_identifier")
        target["email"] = target.get("email") or profile.get("email")
    return list(identities.values())


def reflected_table(connection, metadata: MetaData, table_name: str) -> Table:
    if table_name in metadata.tables:
        return metadata.tables[table_name]
    return Table(table_name, metadata, autoload_with=connection)


def schema_truncation_warnings(connection, metadata: MetaData, rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for table_name, records in rows.items():
        if not records:
            continue
        table = reflected_table(connection, metadata, table_name)
        columns = {column.name: column for column in table.columns}
        for row in records:
            for key, value in row.items():
                column = columns.get(key)
                if column is None:
                    warnings.append({"table": table_name, "column": key, "reason": "mapped column is absent from target schema"})
                elif isinstance(value, str) and column.type.length and len(value) > column.type.length:
                    warnings.append({"table": table_name, "column": key, "reason": "value exceeds target column length"})
    return warnings


def target_key_collisions(connection, metadata: MetaData, rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    collisions: list[dict[str, Any]] = []
    inspector = inspect(connection)
    for table_name, records in rows.items():
        if not records:
            continue
        table = reflected_table(connection, metadata, table_name)
        unique_keys: set[tuple[str, ...]] = set()
        primary_key = tuple(column.name for column in table.primary_key.columns)
        if primary_key:
            unique_keys.add(primary_key)
        for constraint in inspector.get_unique_constraints(table_name):
            columns = tuple(constraint.get("column_names") or ())
            if columns:
                unique_keys.add(columns)
        for index in inspector.get_indexes(table_name):
            columns = tuple(index.get("column_names") or ())
            if index.get("unique") and columns and all(isinstance(name, str) for name in columns) and not (index.get("dialect_options") or {}).get("postgresql_where"):
                unique_keys.add(columns)

        for key_columns in unique_keys:
            if any(any(column not in row for column in key_columns) for row in records):
                continue
            source_keys = [tuple(row[column] for column in key_columns) for row in records]
            source_counts: dict[tuple[Any, ...], int] = {}
            for key in source_keys:
                if any(value is None for value in key):
                    continue
                source_counts[key] = source_counts.get(key, 0) + 1
            duplicate_count = sum(count - 1 for count in source_counts.values() if count > 1)
            columns = [table.c[name] for name in key_columns]
            target_keys: set[tuple[Any, ...]] = set()
            distinct_keys = list(source_counts)
            for start in range(0, len(distinct_keys), 500):
                batch = distinct_keys[start:start + 500]
                if len(columns) == 1:
                    statement = select(*columns).where(columns[0].in_([key[0] for key in batch]))
                else:
                    from sqlalchemy import tuple_
                    statement = select(*columns).where(tuple_(*columns).in_(batch))
                target_keys.update(tuple(row) for row in connection.execute(statement).all())
            collision_count = duplicate_count + len(set(source_counts) & target_keys)
            if collision_count:
                collisions.append({
                    "table": table_name, "key": list(key_columns), "count": collision_count,
                })
    return collisions


def foreign_key_violations(connection, metadata: MetaData, rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for table_name, records in rows.items():
        if not records:
            continue
        child = reflected_table(connection, metadata, table_name)
        for constraint in child.foreign_key_constraints:
            child_names = tuple(element.parent.name for element in constraint.elements)
            parent_names = tuple(element.column.name for element in constraint.elements)
            parent_name = next(iter(constraint.elements)).column.table.name
            parent = reflected_table(connection, metadata, parent_name)
            candidates = [
                tuple(row[name] for name in child_names)
                for row in records
                if all(row.get(name) is not None for name in child_names)
            ]
            if not candidates:
                continue
            mapped_parent_keys = {
                tuple(row.get(name) for name in parent_names)
                for row in rows.get(parent_name, [])
                if all(row.get(name) is not None for name in parent_names)
            }
            unresolved = set(candidates) - mapped_parent_keys
            found: set[tuple[Any, ...]] = set()
            parent_columns = [parent.c[name] for name in parent_names]
            for start in range(0, len(unresolved), 500):
                batch = list(unresolved)[start:start + 500]
                if len(parent_columns) == 1:
                    statement = select(*parent_columns).where(parent_columns[0].in_([key[0] for key in batch]))
                else:
                    from sqlalchemy import tuple_
                    statement = select(*parent_columns).where(tuple_(*parent_columns).in_(batch))
                found.update(tuple(row) for row in connection.execute(statement).all())
            missing_count = sum(1 for key in candidates if key not in mapped_parent_keys and key not in found)
            if missing_count:
                violations.append({"table": table_name, "constraint": constraint.name, "count": missing_count})
    return violations


def insert_rows(connection, metadata: MetaData, table_name: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    table = reflected_table(connection, metadata, table_name)
    allowed = {column.name for column in table.columns}
    if any(set(row) - allowed for row in rows):
        raise RuntimeError(f"Target schema would truncate mapped columns in {table_name}; refusing reconciliation.")
    primary_keys = [column.name for column in table.primary_key.columns]
    if not primary_keys:
        raise RuntimeError(f"Target table {table_name} has no primary key; refusing reconciliation.")
    for start in range(0, len(rows), 250):
        statement = insert(table).values(rows[start:start + 250])
        connection.execute(statement)
    return len(rows)


def verify_source_key_parity(connection, metadata: MetaData, rows: dict[str, list[dict[str, Any]]]) -> None:
    for table_name, records in rows.items():
        if not records:
            continue
        table = reflected_table(connection, metadata, table_name)
        key_columns = tuple(column.name for column in table.primary_key.columns)
        if not key_columns:
            raise RuntimeError(f"Target table {table_name} has no primary key; refusing parity verification.")
        expected = {
            tuple(row[column] for column in key_columns)
            for row in records
        }
        columns = [table.c[name] for name in key_columns]
        if len(columns) == 1:
            found = {
                (value,)
                for value in connection.execute(
                    select(columns[0]).where(columns[0].in_([key[0] for key in expected]))
                ).scalars()
            }
        else:
            from sqlalchemy import tuple_
            found = {
                tuple(row)
                for row in connection.execute(
                    select(*columns).where(tuple_(*columns).in_(list(expected)))
                ).all()
            }
        missing = expected - found
        if missing:
            raise RuntimeError(f"Post-reconciliation parity failed for {table_name}: {len(missing)} source keys missing.")


def finish_transaction(transaction, *, apply: bool) -> str:
    if apply:
        transaction.commit()
        return "committed"
    transaction.rollback()
    return "rolled_back"


def reconcile(
    backup: Path, *, apply: bool, url: str | None,
    approve_disposition_policy: bool = False, approval_reference: str = "",
) -> dict[str, Any]:
    source = read_source(backup)
    warnings = reconciliation_warnings(source)
    summary: dict[str, Any] = {
        "backup": str(backup), "mode": "apply" if apply else "dry-run",
        "tables": {}, "warnings": warnings,
    }
    if not url:
        raise RuntimeError("DATABASE_URL is required for reconciliation. No local fallback is inferred.")
    preflight_database(url)
    engine = create_engine(url, pool_pre_ping=True)
    connection = None
    transaction = None
    try:
        metadata = MetaData()
        connection = engine.connect()
        transaction = connection.begin()
        existing = set(inspect(connection).get_table_names())
        target_suppliers = target_supplier_identities(connection, metadata)
        rows = target_rows(source, target_suppliers=target_suppliers)
        mapping_metrics = rows.pop("_reconciliation")
        for table_name in rows:
            if table_name not in existing:
                raise RuntimeError(f"Target PostgreSQL table is missing: {table_name}. Apply the reviewed quarantine migration first.")

        truncation_warnings = schema_truncation_warnings(connection, metadata, rows)
        collisions = target_key_collisions(connection, metadata, rows)
        fk_violations = foreign_key_violations(connection, metadata, rows)
        summary.update({
            "mapping": mapping_metrics,
            "schema_truncations": truncation_warnings,
            "target_key_collisions": collisions,
            "foreign_key_violations": fk_violations,
            "tables": {
                name: {"source_keys": len(records), "status": "ready" if apply else "would_insert"}
                for name, records in rows.items()
            },
        })
        assert_reconciliation_safe(
            target_key_collisions=sum(item["count"] for item in collisions),
            schema_truncations=len(truncation_warnings),
            foreign_key_violations=sum(item["count"] for item in fk_violations),
        )
        if mapping_metrics["ambiguous_supplier_matches"]:
            raise RuntimeError(
                "Reconciliation safety checks failed; transaction must roll back: "
                f"ambiguous_supplier_matches={mapping_metrics['ambiguous_supplier_matches']}"
            )
        if apply:
            assert_apply_has_complete_source(warnings)
            assert_disposition_approval(
                warnings,
                approved=approve_disposition_policy,
                approval_reference=approval_reference,
            )
            if any(warning["severity"] == "review" for warning in warnings):
                summary["disposition_approval_reference"] = approval_reference.strip()
            for table_name, records in rows.items():
                inserted = insert_rows(connection, metadata, table_name, records)
                summary["tables"][table_name] = {"source_keys": inserted, "status": "inserted"}
            connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            verify_source_key_parity(connection, metadata, rows)
            summary["parity"] = "passed"
        summary["transaction"] = finish_transaction(transaction, apply=apply)
    except IntegrityError as exc:
        if transaction is not None and transaction.is_active:
            transaction.rollback()
        raise RuntimeError(
            "Reconciliation aborted and transaction rolled back after a database constraint violation."
        ) from exc
    except Exception:
        if transaction is not None and transaction.is_active:
            transaction.rollback()
        raise
    finally:
        if connection is not None:
            connection.close()
        engine.dispose()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", type=Path, default=None, help="Timestamped backup directory; defaults to newest local backup")
    parser.add_argument("--apply", action="store_true", help="Insert reconciled rows and commit. Without this option, runs a rolled-back dry run.")
    parser.add_argument("--approve-disposition-policy", action="store_true", help="Confirm the release owner's approved disposition for flagged quote items and supplier profiles.")
    parser.add_argument("--approval-reference", default="", help="Sanitized approval/ticket reference required with --apply when review records exist.")
    parser.add_argument("--plan-only", action="store_true", help="Print source row counts without requiring PostgreSQL connectivity.")
    args = parser.parse_args()
    try:
        backup = args.backup_dir or latest_backup()
        source = read_source(backup)
        mapped = target_rows(source)
        if args.plan_only:
            print(json.dumps({
                "backup": str(backup), "mode": "plan-only",
                "source_tables": {name: len(rows) for name, rows in mapped.items() if name != "_reconciliation"},
                "mapping": mapped["_reconciliation"],
                "warnings": reconciliation_warnings(source),
            }, indent=2))
            return 0
        url = os.getenv("DATABASE_URL", "").strip()
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        result = reconcile(
            backup,
            apply=args.apply,
            url=url or None,
            approve_disposition_policy=args.approve_disposition_policy,
            approval_reference=args.approval_reference,
        )
        print(json.dumps(result, indent=2, default=str))
        return 0
    except Exception as exc:
        print(f"reconciliation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())