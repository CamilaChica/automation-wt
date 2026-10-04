"""Read active business policies for advisory DSPy context."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from models.async_models import BusinessPolicyRecord
from services.async_database import create_sync_engine_from_environment


class BusinessPolicyRetrievalError(RuntimeError):
    """Raised when configured business policies cannot be read safely."""


def retrieve_active_business_policies(
    session_factory: Callable[[], Session] | sessionmaker[Session] | None = None,
) -> list[dict[str, Any]]:
    """Return active policy records; missing or unreadable policy data is an error."""
    owned_engine = None
    if session_factory is None:
        try:
            owned_engine = create_sync_engine_from_environment()
            session_factory = sessionmaker(bind=owned_engine)
        except Exception as exc:
            raise BusinessPolicyRetrievalError(
                "Unable to configure the business-policy database connection."
            ) from exc

    try:
        with session_factory() as session:
            records = session.scalars(
                select(BusinessPolicyRecord)
                .where(BusinessPolicyRecord.is_active.is_(True))
                .order_by(BusinessPolicyRecord.category, BusinessPolicyRecord.policy_key)
            ).all()
            policies = [
                {
                    "policy_key": record.policy_key,
                    "title": record.title,
                    "category": record.category,
                    "description": record.description,
                    "policy_data": record.policy_data or {},
                }
                for record in records
            ]
    except Exception as exc:
        raise BusinessPolicyRetrievalError(
            "Unable to retrieve active business policies."
        ) from exc
    finally:
        if owned_engine is not None:
            owned_engine.dispose()

    if not policies:
        raise BusinessPolicyRetrievalError(
            "No active business policies are available for DSPy evaluation."
        )
    return policies
