from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from agents.supplier_discovery_agent import SupplierDiscoveryAgent
from services.communication_service import CommunicationService


def _offer(email: str, updated_at: str, price: float, source_email_id: str) -> dict:
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
        "source_email_id": source_email_id,
    }


def test_supplier_discovery_excludes_quotes_older_than_30_days():
    now = datetime.now(timezone.utc)
    fresh = _offer("fresh@example.com", now.isoformat(), 1400.0, "fresh-thread")
    stale = _offer("stale@example.com", (now - timedelta(days=31)).isoformat(), 900.0, "stale-thread")

    with patch("agents.supplier_discovery_agent.supplier_db.find_supplier_offers", return_value=[stale, fresh]):
        agent = SupplierDiscoveryAgent()
        results = agent.search_suppliers("READY-QU-965064", 2)

    assert [result["supplier_email"] for result in results] == ["fresh@example.com"]
    assert [offer["supplier_email"] for offer in agent.last_stale_offers] == ["stale@example.com"]


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
