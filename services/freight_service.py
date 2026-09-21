"""Provider-neutral freight rate quoting with a safe dry-run mode."""

from __future__ import annotations

import os
from typing import Any, Dict, List

import requests
from pydantic import BaseModel, Field


class FreightRequest(BaseModel):
    origin: str = Field(..., min_length=1)
    destination: str = Field(..., min_length=1)
    weight_kg: float = Field(..., gt=0)
    packages: int = Field(1, ge=1)
    service_level: str = Field("standard", min_length=1)


class FreightRate(BaseModel):
    service: str = Field(..., min_length=1)
    amount: float = Field(..., ge=0)
    currency: str = "USD"
    estimated_days: int | None = None
    carrier: str | None = None


class FreightRateService:
    def __init__(self):
        self.enabled = os.getenv("FREIGHT_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.base_url = os.getenv("FREIGHT_API_BASE_URL", "").rstrip("/")
        self.api_key = os.getenv("FREIGHT_API_KEY", "").strip()
        self.provider = os.getenv("FREIGHT_PROVIDER", "configured-carrier-api")

    def quote(
        self,
        *,
        origin: str,
        destination: str,
        weight_kg: float,
        packages: int = 1,
        service_level: str = "standard",
    ) -> Dict[str, Any]:
        request_data = FreightRequest(
            origin=origin.strip(),
            destination=destination.strip(),
            weight_kg=weight_kg,
            packages=packages,
            service_level=service_level.strip() or "standard",
        ).model_dump()
        if not self.enabled:
            return {
                "provider": self.provider,
                "status": "DRY_RUN",
                "request": request_data,
                "rates": [],
                "message": "Freight provider is disabled; the shipping charge was not added to the customer quote.",
            }
        if not self.base_url or not self.api_key:
            raise RuntimeError("FREIGHT_API_BASE_URL and FREIGHT_API_KEY are required when freight is enabled.")

        response = requests.post(
            f"{self.base_url}/rates",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=request_data,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        rates = self._normalize_rates(payload)
        return {
            "provider": self.provider,
            "status": "QUOTED",
            "request": request_data,
            "rates": rates,
        }

    @staticmethod
    def _normalize_rates(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        raw_rates = payload.get("rates", [])
        if not isinstance(raw_rates, list):
            raise ValueError("Freight provider returned an invalid rates collection.")
        normalized = []
        for rate in raw_rates:
            if not isinstance(rate, dict):
                continue
            try:
                normalized.append(FreightRate.model_validate(rate).model_dump())
            except ValueError:
                continue
        return sorted(normalized, key=lambda rate: rate["amount"])


freight_rate_service = FreightRateService()
