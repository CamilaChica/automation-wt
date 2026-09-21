"""Deterministic supplier negotiation state and commercial guardrails."""

from __future__ import annotations

from enum import StrEnum
from typing import List

from pydantic import BaseModel, Field, model_validator


class NegotiationState(StrEnum):
    STARTED = "NEGOTIATION_STARTED"
    COUNTEROFFER_SENT = "COUNTEROFFER_SENT"
    SUPPLIER_RESPONSE_RECEIVED = "SUPPLIER_RESPONSE_RECEIVED"
    DISCOUNT_ACCEPTED = "DISCOUNT_ACCEPTED"
    DISCOUNT_REJECTED = "DISCOUNT_REJECTED"
    ESCALATED = "NEGOTIATION_ESCALATED"


class NegotiationRound(BaseModel):
    number: int = Field(..., ge=1)
    requested_unit_cost: float = Field(..., ge=0)
    supplier_unit_cost: float | None = Field(None, ge=0)
    state: NegotiationState
    response_note: str | None = None


class NegotiationSession(BaseModel):
    session_id: str = Field(..., min_length=1)
    supplier_id: str = Field(..., min_length=1)
    part_number: str = Field(..., min_length=1)
    initial_unit_cost: float = Field(..., ge=0)
    minimum_unit_cost: float = Field(..., ge=0)
    maximum_rounds: int = Field(2, ge=1, le=5)
    state: NegotiationState = NegotiationState.STARTED
    rounds: List[NegotiationRound] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_floor(self) -> "NegotiationSession":
        if self.minimum_unit_cost > self.initial_unit_cost:
            raise ValueError("Negotiation floor cannot exceed the initial supplier cost.")
        return self

    def propose(self, requested_unit_cost: float) -> NegotiationRound:
        if self.state in {NegotiationState.DISCOUNT_ACCEPTED, NegotiationState.DISCOUNT_REJECTED, NegotiationState.ESCALATED}:
            raise ValueError("Negotiation is already closed.")
        if len(self.rounds) >= self.maximum_rounds:
            self.state = NegotiationState.ESCALATED
            raise ValueError("Maximum negotiation rounds reached; human review is required.")
        if requested_unit_cost < self.minimum_unit_cost:
            self.state = NegotiationState.ESCALATED
            raise ValueError("Requested supplier cost breaches the deterministic negotiation floor.")
        round_data = NegotiationRound(
            number=len(self.rounds) + 1,
            requested_unit_cost=requested_unit_cost,
            state=NegotiationState.COUNTEROFFER_SENT,
        )
        self.rounds.append(round_data)
        self.state = NegotiationState.COUNTEROFFER_SENT
        return round_data

    def record_response(self, supplier_unit_cost: float, accepted: bool, note: str | None = None) -> NegotiationRound:
        if not self.rounds or self.state != NegotiationState.COUNTEROFFER_SENT:
            raise ValueError("A supplier response requires an outstanding counteroffer.")
        if supplier_unit_cost < self.minimum_unit_cost:
            self.state = NegotiationState.ESCALATED
            raise ValueError("Supplier response breaches the deterministic negotiation floor.")
        current = self.rounds[-1]
        current.supplier_unit_cost = supplier_unit_cost
        current.response_note = note
        current.state = NegotiationState.DISCOUNT_ACCEPTED if accepted else NegotiationState.SUPPLIER_RESPONSE_RECEIVED
        self.state = current.state
        if not accepted and current.number >= self.maximum_rounds:
            self.state = NegotiationState.DISCOUNT_REJECTED
            current.state = NegotiationState.DISCOUNT_REJECTED
        return current
