"""SQLite-backed, validated context for grounded email generation."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EmailGroundingContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_email: str = Field(..., min_length=3)
    company_name: str = Field(..., min_length=1)
    contact_name: str = Field(..., min_length=1)
    part_number: str = Field(..., min_length=1)
    quantity: int = Field(..., gt=0)
    condition: str | None = None
    certification: str | None = None
    lead_time: int | None = Field(None, ge=0)
    unit_price: float | None = Field(None, ge=0)
    currency: str = "USD"

    @property
    def lead_time_label(self) -> str:
        return f"{self.lead_time} days" if self.lead_time is not None else "available upon request"


class EmailContextRepository:
    """Loads fresh email facts per call; it intentionally has no record cache."""

    def __init__(self, database_path: str):
        self.database_path = database_path

    def customer_quote_context(self, quote_id: str) -> EmailGroundingContext:
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT c.email AS recipient_email, c.company_name, c.contact_name,
                       r.part_number, cq.quantity, cq.condition, cq.certification,
                       cq.lead_time, cq.unit_price, cq.currency
                FROM customer_quotes cq
                JOIN rfqs r ON r.id = cq.rfq_id
                JOIN customers c ON c.id = r.customer_id
                WHERE cq.id = ?
                """,
                (quote_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"Customer quote '{quote_id}' was not found.")
        return EmailGroundingContext.model_validate(dict(row))

    def supplier_quote_context(self, quote_id: str) -> EmailGroundingContext:
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT s.email AS recipient_email, s.company_name, s.contact_name,
                       sq.part_number, sq.quantity, sq.condition, sq.certification,
                       sq.lead_time, sq.unit_price, sq.currency
                FROM supplier_quotes sq
                JOIN suppliers s ON s.id = sq.supplier_id
                WHERE sq.id = ?
                """,
                (quote_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"Supplier quote '{quote_id}' was not found.")
        return EmailGroundingContext.model_validate(dict(row))


def safe_display_text(value: str, *, fallback: str = "there") -> str:
    """Remove control characters and prompt-like instruction text from display fields."""
    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))
    cleaned = re.sub(r"\b(ignore|disregard)\s+(all\s+)?previous\s+instructions?\b.*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:120] or fallback
