"""Deterministic supplier negotiation state and commercial guardrails."""

from __future__ import annotations

import hashlib
import os
from enum import StrEnum
from typing import Any, Callable, List

from pydantic import BaseModel, Field, model_validator

from services.operations_store import operations_store


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


class SupplierNegotiationService:
    def __init__(self, schedule_request: Callable[..., Any] | None = None):
        self.schedule_request = schedule_request

    def _schedule(self, *, recipient: str, supplier_name: str, part_number: str, unit_cost: float, session_id: str, round_number: int, quantity: int, reply_to: str | None, supplier_sentiment: dict[str, Any] | None) -> Any:
        schedule = self.schedule_request
        if schedule is None:
            from services.communication_service import communication_service
            schedule = communication_service.schedule_supplier_discount_request
        return schedule(
            recipient=recipient,
            supplier_name=supplier_name,
            part_number=part_number,
            unit_cost=unit_cost,
            source_email_id=session_id,
            reply_to=reply_to,
            round_number=round_number,
            quantity=quantity,
            supplier_sentiment=supplier_sentiment,
        )

    def record_supplier_quote(
        self,
        *,
        supplier_email: str,
        supplier_name: str,
        part_number: str,
        quantity: int,
        unit_cost: float,
        source_email_id: str,
        reply_to: str | None = None,
        supplier_sentiment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        email = supplier_email.strip().lower()
        part = part_number.strip().upper()
        if not email or not part or quantity <= 0 or unit_cost <= 0:
            return {"status": "INVALID_QUOTE"}
        threshold = max(0.0, float(os.getenv("NEGOTIATION_MIN_LINE_VALUE", "500")))
        session_payload = operations_store.get_negotiation_session(email, part)
        if session_payload is None:
            if quantity * unit_cost < threshold:
                return {"status": "BELOW_THRESHOLD"}
            max_rounds = min(5, max(1, int(os.getenv("SUPPLIER_DISCOUNT_MAX_ROUNDS", "3"))))
            floor_discount = min(90.0, max(0.0, float(os.getenv("NEGOTIATION_FLOOR_DISCOUNT_PERCENT", "10"))))
            first_discount = min(floor_discount, max(0.0, float(os.getenv("NEGOTIATION_FIRST_DISCOUNT_PERCENT", "5"))))
            session_id = "NEG-" + hashlib.sha256(f"{email}\0{part}".encode()).hexdigest()[:20].upper()
            session = NegotiationSession(
                session_id=session_id,
                supplier_id=email,
                part_number=part,
                initial_unit_cost=unit_cost,
                minimum_unit_cost=unit_cost * (1 - floor_discount / 100),
                maximum_rounds=max_rounds,
            )
            round_data = session.propose(max(session.minimum_unit_cost, unit_cost * (1 - first_discount / 100)))
            session_payload = {
                "session": session.model_dump(mode="json"),
                "supplier_name": supplier_name,
                "quantity": quantity,
                "reply_to": reply_to,
                "source_email_id": source_email_id,
                "supplier_sentiment": supplier_sentiment,
            }
            operations_store.save_negotiation_session(
                session_id=session_id, supplier_email=email, part_number=part, payload=session_payload,
            )
            self._schedule(
                recipient=email, supplier_name=supplier_name, part_number=part,
                unit_cost=round_data.requested_unit_cost, session_id=session_id,
                round_number=round_data.number, quantity=quantity, reply_to=reply_to,
                supplier_sentiment=supplier_sentiment,
            )
            return {"status": "COUNTEROFFER_SENT", "round": round_data.number, "session_id": session_id}

        session = NegotiationSession.model_validate(session_payload["session"])
        if source_email_id and session_payload.get("source_email_id") == source_email_id:
            return {"status": "DUPLICATE_EMAIL", "session_id": session.session_id}
        if session.state != NegotiationState.COUNTEROFFER_SENT:
            return {"status": session.state.value, "session_id": session.session_id}
        try:
            current_round = session.rounds[-1]
            session.record_response(
                unit_cost,
                accepted=unit_cost <= current_round.requested_unit_cost,
                note=f"Supplier reply {source_email_id}",
            )
        except ValueError:
            session.state = NegotiationState.ESCALATED
            session_payload["session"] = session.model_dump(mode="json")
            operations_store.save_negotiation_session(
                session_id=session.session_id, supplier_email=email, part_number=part, payload=session_payload,
            )
            return {"status": session.state.value, "session_id": session.session_id}

        next_round = None
        if session.state == NegotiationState.SUPPLIER_RESPONSE_RECEIVED and len(session.rounds) < session.maximum_rounds:
            step = min(50.0, max(0.0, float(os.getenv("NEGOTIATION_NEXT_DISCOUNT_PERCENT", "3"))))
            requested = max(session.minimum_unit_cost, current_round.requested_unit_cost * (1 - step / 100))
            if requested >= current_round.requested_unit_cost:
                session.state = NegotiationState.ESCALATED
            else:
                next_round = session.propose(requested)

        session_payload["session"] = session.model_dump(mode="json")
        session_payload["source_email_id"] = source_email_id
        session_payload["supplier_sentiment"] = supplier_sentiment
        operations_store.save_negotiation_session(
            session_id=session.session_id, supplier_email=email, part_number=part, payload=session_payload,
        )
        if next_round:
            self._schedule(
                recipient=email,
                supplier_name=str(session_payload.get("supplier_name") or supplier_name),
                part_number=part,
                unit_cost=next_round.requested_unit_cost,
                session_id=session.session_id,
                round_number=next_round.number,
                quantity=int(session_payload.get("quantity") or quantity),
                reply_to=reply_to or session_payload.get("reply_to"),
                supplier_sentiment=supplier_sentiment,
            )
        return {"status": session.state.value, "round": len(session.rounds), "session_id": session.session_id}

    async def record_supplier_quote_async(
        self,
        repositories,
        *,
        supplier_email: str,
        supplier_name: str,
        part_number: str,
        quantity: int,
        unit_cost: float,
        source_email_id: str,
        reply_to: str | None = None,
        supplier_sentiment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        email = supplier_email.strip().lower()
        part = part_number.strip().upper()
        if not email or not part or quantity <= 0 or unit_cost <= 0:
            return {"status": "INVALID_QUOTE"}
        threshold = max(0.0, float(os.getenv("NEGOTIATION_MIN_LINE_VALUE", "500")))
        session_payload = await repositories.records.get_negotiation_session(email, part)
        if session_payload is None:
            if quantity * unit_cost < threshold:
                return {"status": "BELOW_THRESHOLD"}
            max_rounds = min(5, max(1, int(os.getenv("SUPPLIER_DISCOUNT_MAX_ROUNDS", "3"))))
            floor_discount = min(90.0, max(0.0, float(os.getenv("NEGOTIATION_FLOOR_DISCOUNT_PERCENT", "10"))))
            first_discount = min(floor_discount, max(0.0, float(os.getenv("NEGOTIATION_FIRST_DISCOUNT_PERCENT", "5"))))
            session_id = "NEG-" + hashlib.sha256(f"{email}\0{part}".encode()).hexdigest()[:20].upper()
            negotiation = NegotiationSession(
                session_id=session_id,
                supplier_id=email,
                part_number=part,
                initial_unit_cost=unit_cost,
                minimum_unit_cost=unit_cost * (1 - floor_discount / 100),
                maximum_rounds=max_rounds,
            )
            round_data = negotiation.propose(max(
                negotiation.minimum_unit_cost,
                unit_cost * (1 - first_discount / 100),
            ))
            session_payload = {
                "session": negotiation.model_dump(mode="json"),
                "supplier_name": supplier_name,
                "quantity": quantity,
                "reply_to": reply_to,
                "source_email_id": source_email_id,
                "supplier_sentiment": supplier_sentiment,
            }
            await repositories.records.save_negotiation_session(
                session_id=session_id, supplier_email=email, part_number=part, payload=session_payload,
            )
            await self._schedule_async(
                repositories, recipient=email, supplier_name=supplier_name, part_number=part,
                unit_cost=round_data.requested_unit_cost, session_id=session_id,
                round_number=round_data.number, quantity=quantity, reply_to=reply_to,
                supplier_sentiment=supplier_sentiment,
            )
            return {"status": "COUNTEROFFER_SENT", "round": round_data.number, "session_id": session_id}

        negotiation = NegotiationSession.model_validate(session_payload["session"])
        if source_email_id and session_payload.get("source_email_id") == source_email_id:
            return {"status": "DUPLICATE_EMAIL", "session_id": negotiation.session_id}
        if negotiation.state != NegotiationState.COUNTEROFFER_SENT:
            return {"status": negotiation.state.value, "session_id": negotiation.session_id}
        try:
            current_round = negotiation.rounds[-1]
            negotiation.record_response(
                unit_cost,
                accepted=unit_cost <= current_round.requested_unit_cost,
                note=f"Supplier reply {source_email_id}",
            )
        except ValueError:
            negotiation.state = NegotiationState.ESCALATED
            session_payload["session"] = negotiation.model_dump(mode="json")
            await repositories.records.save_negotiation_session(
                session_id=negotiation.session_id, supplier_email=email, part_number=part, payload=session_payload,
            )
            return {"status": negotiation.state.value, "session_id": negotiation.session_id}

        next_round = None
        if negotiation.state == NegotiationState.SUPPLIER_RESPONSE_RECEIVED and len(negotiation.rounds) < negotiation.maximum_rounds:
            step = min(50.0, max(0.0, float(os.getenv("NEGOTIATION_NEXT_DISCOUNT_PERCENT", "3"))))
            requested = max(negotiation.minimum_unit_cost, current_round.requested_unit_cost * (1 - step / 100))
            if requested >= current_round.requested_unit_cost:
                negotiation.state = NegotiationState.ESCALATED
            else:
                next_round = negotiation.propose(requested)

        session_payload["session"] = negotiation.model_dump(mode="json")
        session_payload["source_email_id"] = source_email_id
        session_payload["supplier_sentiment"] = supplier_sentiment
        await repositories.records.save_negotiation_session(
            session_id=negotiation.session_id, supplier_email=email, part_number=part, payload=session_payload,
        )
        if next_round:
            await self._schedule_async(
                repositories,
                recipient=email,
                supplier_name=str(session_payload.get("supplier_name") or supplier_name),
                part_number=part,
                unit_cost=next_round.requested_unit_cost,
                session_id=negotiation.session_id,
                round_number=next_round.number,
                quantity=int(session_payload.get("quantity") or quantity),
                reply_to=reply_to or session_payload.get("reply_to"),
                supplier_sentiment=supplier_sentiment,
            )
        return {"status": negotiation.state.value, "round": len(negotiation.rounds), "session_id": negotiation.session_id}

    @staticmethod
    async def _schedule_async(
        repositories,
        *,
        recipient: str,
        supplier_name: str,
        part_number: str,
        unit_cost: float,
        session_id: str,
        round_number: int,
        quantity: int,
        reply_to: str | None,
        supplier_sentiment: dict[str, Any] | None,
    ) -> Any:
        from services.communication_service import communication_service

        return await communication_service.schedule_supplier_discount_request_async(
            repositories,
            recipient=recipient,
            supplier_name=supplier_name,
            part_number=part_number,
            unit_cost=unit_cost,
            source_email_id=session_id,
            reply_to=reply_to,
            round_number=round_number,
            quantity=quantity,
            supplier_sentiment=supplier_sentiment,
        )
