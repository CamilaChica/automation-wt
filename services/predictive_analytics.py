"""Deterministic predictive signals for sourcing and inventory decisions."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field, computed_field


class SupplierReliabilityInput(BaseModel):
    completed_orders: int = Field(0, ge=0)
    on_time_deliveries: int = Field(0, ge=0)
    returns: int = Field(0, ge=0)
    average_lead_time_days: float = Field(0, ge=0)
    lead_time_variance_days: float = Field(0, ge=0)

    @computed_field
    @property
    def delivery_rate(self) -> float:
        if self.completed_orders == 0:
            return 0.5
        return min(self.on_time_deliveries / self.completed_orders, 1.0)

    @computed_field
    @property
    def return_rate(self) -> float:
        if self.completed_orders == 0:
            return 0.0
        return min(self.returns / self.completed_orders, 1.0)


class SupplierReliabilityScore(BaseModel):
    score: float = Field(..., ge=0, le=100)
    confidence: float = Field(..., ge=0, le=1)
    risk_level: str
    reasons: List[str]


def score_supplier_reliability(signals: SupplierReliabilityInput) -> SupplierReliabilityScore:
    delivery_component = signals.delivery_rate
    return_component = 1.0 - signals.return_rate
    consistency_component = max(0.0, 1.0 - min(signals.lead_time_variance_days / 14.0, 1.0))
    score = round((delivery_component * 0.55 + return_component * 0.25 + consistency_component * 0.20) * 100, 2)
    confidence = min(signals.completed_orders / 10.0, 1.0)
    reasons: List[str] = []
    if signals.completed_orders == 0:
        reasons.append("No completed order history; reliability is an estimate.")
    if signals.delivery_rate < 0.9:
        reasons.append("On-time delivery performance is below the 90% target.")
    if signals.return_rate > 0.05:
        reasons.append("Return rate exceeds the 5% review threshold.")
    if signals.lead_time_variance_days > 7:
        reasons.append("Lead-time variance exceeds the 7-day stability threshold.")
    if not reasons:
        reasons.append("Supplier history is within reliability thresholds.")
    risk_level = "LOW" if score >= 80 else "MEDIUM" if score >= 60 else "HIGH"
    return SupplierReliabilityScore(
        score=score,
        confidence=round(confidence, 2),
        risk_level=risk_level,
        reasons=reasons,
    )


class DemandRiskInput(BaseModel):
    requests_last_30_days: int = Field(0, ge=0)
    aog_requests_last_30_days: int = Field(0, ge=0)
    requested_quantity_last_30_days: int = Field(0, ge=0)
    available_quantity: int = Field(0, ge=0)
    active_supplier_count: int = Field(0, ge=0)
    average_lead_time_days: float = Field(0, ge=0)


class DemandRiskScore(BaseModel):
    score: float = Field(..., ge=0, le=100)
    risk_level: str
    recommended_action: str
    reasons: List[str]


def score_demand_risk(signals: DemandRiskInput) -> DemandRiskScore:
    requested = max(signals.requested_quantity_last_30_days, 1)
    scarcity = max(0.0, 1.0 - min(signals.available_quantity / requested, 1.0))
    aog_pressure = min(signals.aog_requests_last_30_days / max(signals.requests_last_30_days, 1), 1.0)
    supplier_concentration = 1.0 if signals.active_supplier_count == 0 else min(1.0 / signals.active_supplier_count, 1.0)
    lead_time_pressure = min(signals.average_lead_time_days / 30.0, 1.0)
    score = round((scarcity * 0.45 + aog_pressure * 0.25 + supplier_concentration * 0.15 + lead_time_pressure * 0.15) * 100, 2)
    reasons: List[str] = []
    if scarcity >= 0.5:
        reasons.append("Available quantity covers less than half of recent requested volume.")
    if aog_pressure > 0.2:
        reasons.append("AOG demand is elevated relative to total recent demand.")
    if signals.active_supplier_count <= 1:
        reasons.append("Sourcing depends on zero or one active supplier.")
    if signals.average_lead_time_days > 14:
        reasons.append("Average lead time exceeds the two-week planning threshold.")
    if not reasons:
        reasons.append("Current demand and supply signals are within planning thresholds.")
    risk_level = "LOW" if score < 35 else "MEDIUM" if score < 65 else "HIGH"
    action = "MONITOR" if risk_level == "LOW" else "PRE_SOURCE" if risk_level == "MEDIUM" else "ESCALATE_AND_PRE_SOURCE"
    return DemandRiskScore(score=score, risk_level=risk_level, recommended_action=action, reasons=reasons)
