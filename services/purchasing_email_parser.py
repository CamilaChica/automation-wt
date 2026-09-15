import re
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from services.relational_db import DEFAULT_DB_PATH, db_connection, ensure_schema, normalize_part_number, utc_now_iso

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


@dataclass(frozen=True)
class ParsedSupplierQuote:
    supplier_email: str
    raw_part_number: str
    clean_part_number: str
    condition: str
    unit_cost_usd: float
    quantity_available: int
    lead_time_days: int
    description: str
    location: str


def _extract_required(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"Could not parse required field: {label}")
    return match.group(1).strip()


def parse_supplier_quote_email(raw_email: str, fallback_from_email: str | None = None) -> ParsedSupplierQuote:
    supplier_email = fallback_from_email
    from_match = re.search(r"^From:\s*(.+)$", raw_email, flags=re.IGNORECASE | re.MULTILINE)
    if from_match:
        email_match = EMAIL_RE.search(from_match.group(1))
        if email_match:
            supplier_email = email_match.group(0).lower()
    if not supplier_email:
        any_email = EMAIL_RE.search(raw_email)
        if any_email:
            supplier_email = any_email.group(0).lower()
    if not supplier_email:
        raise ValueError("Supplier email could not be determined from the message")

    raw_part_number = _extract_required(r"part(?:\s*number)?\s*[:=]\s*([^\r\n]+)", raw_email, "part_number")
    condition = _extract_required(r"condition\s*[:=]\s*([A-Za-z]{2,3})", raw_email, "condition").upper()
    quantity = int(_extract_required(r"quantity\s*[:=]\s*(\d+)", raw_email, "quantity"))
    unit_cost = float(_extract_required(r"(?:price|unit\s*cost)\s*[:=]\s*\$?([0-9]+(?:\.[0-9]{1,2})?)", raw_email, "price"))
    lead_time_days = int(_extract_required(r"lead[_\s-]*time(?:\s*days)?\s*[:=]\s*(\d+)", raw_email, "lead_time"))

    description_match = re.search(r"description\s*[:=]\s*(.+)$", raw_email, flags=re.IGNORECASE | re.MULTILINE)
    location_match = re.search(r"location\s*[:=]\s*(.+)$", raw_email, flags=re.IGNORECASE | re.MULTILINE)

    return ParsedSupplierQuote(
        supplier_email=supplier_email,
        raw_part_number=raw_part_number,
        clean_part_number=normalize_part_number(raw_part_number),
        condition=condition,
        unit_cost_usd=unit_cost,
        quantity_available=quantity,
        lead_time_days=lead_time_days,
        description=description_match.group(1).strip() if description_match else "Supplier quoted part",
        location=location_match.group(1).strip() if location_match else "Supplier warehouse",
    )


def _supplier_name_from_email(supplier_email: str) -> str:
    local_part = supplier_email.split("@", 1)[0]
    words = [token for token in re.split(r"[._\-]+", local_part) if token]
    if not words:
        return "Auto Supplier"
    return " ".join(word.capitalize() for word in words)


def _find_or_create_supplier(connection: sqlite3.Connection, supplier_email: str) -> str:
    existing = connection.execute(
        "SELECT id FROM suppliers WHERE email = ?",
        (supplier_email.lower(),),
    ).fetchone()
    if existing:
        return str(existing["id"])

    supplier_id = f"SUP-{uuid.uuid4().hex[:8].upper()}"
    connection.execute(
        """
        INSERT INTO suppliers (id, name, email, phone, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            supplier_id,
            _supplier_name_from_email(supplier_email),
            supplier_email.lower(),
            "",
            utc_now_iso(),
        ),
    )
    return supplier_id


def ingest_supplier_quote_email(raw_email: str, source_email_id: str, db_path: Path = DEFAULT_DB_PATH) -> dict[str, str]:
    ensure_schema(db_path)
    parsed = parse_supplier_quote_email(raw_email)

    with db_connection(db_path) as connection:
        already_processed = connection.execute(
            "SELECT source_email_id FROM purchasing_email_ingestion WHERE source_email_id = ?",
            (source_email_id,),
        ).fetchone()
        if already_processed:
            existing = connection.execute(
                """
                SELECT i.supplier_id, e.inventory_item_id
                FROM purchasing_email_ingestion e
                JOIN inventory_items i ON i.id = e.inventory_item_id
                WHERE e.source_email_id = ?
                """,
                (source_email_id,),
            ).fetchone()
            return {
                "supplier_id": str(existing["supplier_id"]),
                "inventory_item_id": str(existing["inventory_item_id"]),
                "clean_part_number": parsed.clean_part_number,
                "condition": parsed.condition,
            }

        supplier_id = _find_or_create_supplier(connection, parsed.supplier_email)
        inventory_id = f"INV-{uuid.uuid4().hex[:8].upper()}"
        now = utc_now_iso()

        connection.execute(
            """
            INSERT INTO inventory_items (
                id, supplier_id, raw_part_number, clean_part_number, description, condition,
                quantity_available, unit_cost_usd, location, lead_time_days, source_email_id, last_updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(supplier_id, clean_part_number, condition)
            DO UPDATE SET
                raw_part_number = excluded.raw_part_number,
                description = excluded.description,
                quantity_available = excluded.quantity_available,
                unit_cost_usd = excluded.unit_cost_usd,
                location = excluded.location,
                lead_time_days = excluded.lead_time_days,
                source_email_id = excluded.source_email_id,
                last_updated_at = excluded.last_updated_at
            """,
            (
                inventory_id,
                supplier_id,
                parsed.raw_part_number,
                parsed.clean_part_number,
                parsed.description,
                parsed.condition,
                parsed.quantity_available,
                parsed.unit_cost_usd,
                parsed.location,
                parsed.lead_time_days,
                source_email_id,
                now,
            ),
        )

        row = connection.execute(
            """
            SELECT id
            FROM inventory_items
            WHERE supplier_id = ? AND clean_part_number = ? AND condition = ?
            """,
            (supplier_id, parsed.clean_part_number, parsed.condition),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO purchasing_email_ingestion (source_email_id, supplier_email, inventory_item_id, processed_at)
            VALUES (?, ?, ?, ?)
            """,
            (source_email_id, parsed.supplier_email.lower(), row["id"], now),
        )

    return {
        "supplier_id": supplier_id,
        "inventory_item_id": str(row["id"]),
        "clean_part_number": parsed.clean_part_number,
        "condition": parsed.condition,
    }


def ingest_supplier_quote_messages(messages: list[dict[str, str]], db_path: Path = DEFAULT_DB_PATH) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for message in messages:
        source_email_id = message.get("message_id", "").strip()
        raw_email = message.get("raw_email", "")
        if not source_email_id or not raw_email:
            continue
        try:
            results.append(ingest_supplier_quote_email(raw_email, source_email_id, db_path))
        except ValueError:
            # Non-quote emails in the purchasing inbox are expected; keep polling.
            continue
    return results
