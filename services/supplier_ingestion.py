from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.ai_router import AIRouter
from services.db_service import MockDatabaseService, db_service
from services.relational_db import DEFAULT_DB_PATH, db_connection, ensure_schema, normalize_part_number


@dataclass(frozen=True)
class ParsedSupplierPayload:
    supplier_email: str
    part_number: str
    condition: str
    unit_cost: float
    quantity_available: int
    lead_time_days: int
    certificate_type: str


def _validate_parsed_payload(payload: dict[str, Any]) -> ParsedSupplierPayload:
    supplier_email = str(payload.get("supplier_email", "")).strip().lower()
    part_number = normalize_part_number(str(payload.get("part_number", "")).strip())
    condition = str(payload.get("condition", "NE")).strip().upper()
    certificate_type = str(payload.get("certificate_type", "Unknown")).strip() or "Unknown"

    if not supplier_email:
        raise ValueError("Parsed payload is missing supplier_email")
    if not part_number:
        raise ValueError("Parsed payload is missing part_number")

    unit_cost = float(payload.get("unit_cost", 0.0))
    quantity_available = int(payload.get("quantity_available", 0))
    lead_time_days = int(payload.get("lead_time_days", 0))

    if unit_cost < 0:
        raise ValueError("unit_cost must be >= 0")
    if quantity_available < 0:
        raise ValueError("quantity_available must be >= 0")
    if lead_time_days < 0:
        raise ValueError("lead_time_days must be >= 0")

    return ParsedSupplierPayload(
        supplier_email=supplier_email,
        part_number=part_number,
        condition=condition,
        unit_cost=unit_cost,
        quantity_available=quantity_available,
        lead_time_days=lead_time_days,
        certificate_type=certificate_type,
    )


def ingest_supplier_quote_email(
    *,
    source_email_id: str,
    raw_quote_text: str,
    ai_router: AIRouter | None = None,
    database: MockDatabaseService | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    if not source_email_id.strip():
        raise ValueError("source_email_id is required")
    if not raw_quote_text.strip():
        raise ValueError("raw_quote_text is required")

    router = ai_router or AIRouter()
    db = database or db_service

    parsed_envelope = router.parse_rfq(raw_quote_text)
    parsed_payload = _validate_parsed_payload(parsed_envelope["result"])

    supplier = db.get_or_create_supplier_by_email(parsed_payload.supplier_email)
    inventory_item = db.upsert_inventory_item_by_part_condition(
        part_number=parsed_payload.part_number,
        condition_code=parsed_payload.condition,
        unit_cost=parsed_payload.unit_cost,
        quantity_available=parsed_payload.quantity_available,
        certificate_type=parsed_payload.certificate_type,
        supplier_id=supplier.id,
        lead_time_days=parsed_payload.lead_time_days,
    )

    audit_payload = {
        "source_email_id": source_email_id,
        "provider": parsed_envelope["provider"],
        "model": parsed_envelope["model"],
        "fallback_used": parsed_envelope["fallback_used"],
        "parsed": parsed_payload.__dict__,
        "supplier_id": supplier.id,
        "inventory_item_id": inventory_item.id,
    }
    db.add_audit_log(
        rfq_id=f"INGEST-{source_email_id}",
        agent_name="SupplierIngestionService",
        action="supplier_quote_ingest",
        message=f"Ingested supplier quote for {parsed_payload.part_number} from {parsed_payload.supplier_email}",
        status="SUCCESS",
        payload=json.dumps(audit_payload),
    )

    ensure_schema(db_path)
    with db_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO agent_audit_logs (event_type, status, payload_json)
            VALUES (?, ?, ?)
            """,
            ("SUPPLIER_INGESTION", "SUCCESS", json.dumps(audit_payload)),
        )

    return {
        "source_email_id": source_email_id,
        "supplier_id": supplier.id,
        "inventory_item_id": inventory_item.id,
        "provider": parsed_envelope["provider"],
        "model": parsed_envelope["model"],
        "fallback_used": parsed_envelope["fallback_used"],
        "parsed": parsed_payload.__dict__,
    }
