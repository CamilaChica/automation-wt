"""Canonical supplier registry and offer payload schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SupplierRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    company_name: str = Field(min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=64)
    approval_status: str = Field(default="Pending", max_length=32)
    itar_certified: bool = False
    source: str = Field(default="email", max_length=32)


class SupplierOfferEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    supplier_id: str = Field(min_length=1, max_length=64)
    part_number: str = Field(min_length=1, max_length=80)
    condition_code: str | None = Field(default=None, max_length=8)
    description: str | None = None
    quantity_available: int | None = Field(default=None, ge=0)
    unit_cost: float | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    certificate_type: str | None = Field(default=None, max_length=128)
    lead_time_days: int | None = Field(default=None, ge=0)
    availability_location: str | None = Field(default=None, max_length=255)
    warranty_terms: str | None = None
    source_email_id: str | None = Field(default=None, max_length=512)
    confidence: float | None = Field(default=None, ge=0, le=1)
    approval_status: str = Field(default="Pending", max_length=32)