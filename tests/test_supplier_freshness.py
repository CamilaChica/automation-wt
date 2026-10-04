from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from agents.supplier_discovery_agent import SupplierDiscoveryAgent
from services.communication_service import CommunicationService


def _offer(
    email: str,
    updated_at: str,
    price: float,
    source_email_id: str,
    source_received_at: str | None = None,
) -> dict:
    return {
        "supplier_id": email,
        "supplier_name": email.split("@", 1)[0].title(),
        "supplier_email": email,
        "part_number": "822-1287-121",
        "quantity_available": 4,
        "unit_cost": price,
        "certificate_type": "FAA 8130-3",
        "lead_time_days": 5,
        "approval_status": "Approved",
        "confidence": 0.95,
        "updated_at": updated_at,
        "source_received_at": source_received_at if source_received_at is not None else updated_at,
        "source_email_id": source_email_id,
    }


def test_supplier_discovery_excludes_quotes_older_than_30_days():
    now = datetime.now(timezone.utc)
    fresh = _offer("fresh@example.com", now.isoformat(), 1400.0, "fresh-thread")
    stale = _offer(
        "stale@example.com",
        now.isoformat(),
        900.0,
        "stale-thread",
        source_received_at=(now - timedelta(days=31)).isoformat(),
    )
    unknown_age = _offer("unknown@example.com", now.isoformat(), 800.0, "unknown-date", None)
    unknown_age.pop("source_received_at")

    with patch(
        "agents.supplier_discovery_agent.supplier_db.find_supplier_offers",
        return_value=[stale, fresh, unknown_age],
    ):
        agent = SupplierDiscoveryAgent()
        results = agent.search_suppliers("READY-QU-965064", 2)

    assert [result["supplier_email"] for result in results] == ["fresh@example.com"]
    assert {offer["supplier_email"] for offer in agent.last_stale_offers} == {
        "stale@example.com",
        "unknown@example.com",
    }


def test_exact_30_day_boundary_uses_source_email_timestamp():
    now = datetime(2026, 1, 31, 12, tzinfo=timezone.utc)
    at_boundary = _offer("boundary@example.com", now.isoformat(), 1400, "boundary",
                         (now - timedelta(days=30)).isoformat())
    expired = _offer("expired@example.com", now.isoformat(), 1300, "expired",
                     (now - timedelta(days=30, microseconds=1)).isoformat())
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    with (
        patch("agents.supplier_discovery_agent.datetime", FrozenDateTime),
        patch("agents.supplier_discovery_agent.operations_store", SimpleNamespace(storage_engine="sqlite")),
        patch("agents.supplier_discovery_agent.supplier_db.find_supplier_offers",
              return_value=[expired, at_boundary]),
    ):
        agent = SupplierDiscoveryAgent()
        results = agent.search_suppliers("822-1287-121", 2)
    assert [result["supplier_email"] for result in results] == ["boundary@example.com"]
    assert agent.last_stale_offers == [expired]


def test_sqlite_offer_history_is_idempotent_per_source_email(tmp_path):
    from services.supplier_database import SupplierDatabase

    database = SupplierDatabase(tmp_path / "supplier-history.db")
    received_at = datetime.now(timezone.utc) - timedelta(days=31)
    shared = {
        "supplier_name": "History Supplier",
        "supplier_email": "quotes@history.example",
        "part_number": "HISTORY-001",
        "quantity_available": 3,
        "unit_cost": 100.0,
        "certificate_type": "FAA 8130-3",
        "lead_time_days": 4,
        "approval_status": "Approved",
    }

    database.save_supplier_offer(
        **shared,
        source_email_id="historical-message",
        source_received_at=received_at,
    )
    database.save_supplier_offer(
        **{**shared, "unit_cost": 110.0},
        source_email_id="historical-message",
        source_received_at=datetime.now(timezone.utc),
    )
    database.save_supplier_offer(
        **{**shared, "unit_cost": 120.0},
        source_email_id="newer-message",
        source_received_at=datetime.now(timezone.utc),
    )

    offers = database.find_supplier_offers("HISTORY-001")
    historical = [offer for offer in offers if offer["source_email_id"] == "historical-message"]
    assert len(historical) == 1
    assert historical[0]["unit_cost"] == 110.0
    assert historical[0]["source_received_at"] == received_at.isoformat()
    assert {offer["source_email_id"] for offer in offers} == {
        "historical-message",
        "newer-message",
    }


def test_supplier_confirmation_replies_in_original_thread():
    service = CommunicationService()
    with patch.object(service, "_send", return_value={"transmission_status": "DRY_RUN"}) as send:
        service.request_stale_supplier_confirmation(
            recipient="sales@wyattaerospace.com",
            supplier_name="Wyatt Aerospace",
            part_number="READY-QU-965064",
            quantity=4,
            reply_to="original-graph-message-id",
        )

    assert send.call_args.args[1] == "sales@wyattaerospace.com"
    assert "READY-QU-965064" in send.call_args.args[2]
    assert "still available" in send.call_args.args[3]
    assert send.call_args.kwargs["reply_to"] == "original-graph-message-id"


def test_unreadable_pdf_request_asks_for_quote_details_in_body():
    service = CommunicationService()
    with patch.object(service, "_send", return_value={"transmission_status": "DRY_RUN"}) as send:
        service.request_supplier_body_quote(
            recipient="sales@wyattaerospace.com",
            part_reference="Quote attached",
            reply_to="pdf-message-id",
        )

    assert send.call_args.args[1] == "sales@wyattaerospace.com"
    assert "Part number" in send.call_args.args[3]
    assert "reply in this same email thread" in send.call_args.args[3]
    assert send.call_args.kwargs["reply_to"] == "pdf-message-id"
