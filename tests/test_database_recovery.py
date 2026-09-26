from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.async_database import _database_url, preflight_database
from services.communication_service import CommunicationService


def test_database_url_uses_only_explicit_fallback_on_dns_failure(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@postgres.internal/app")
    monkeypatch.setenv("DATABASE_URL_FALLBACK", "postgresql://local-user:local-pass@127.0.0.1/app")
    monkeypatch.setattr("services.async_database.socket.getaddrinfo", Mock(side_effect=socket.gaierror()))

    assert _database_url() == "postgresql+asyncpg://local-user:local-pass@127.0.0.1/app"


def test_database_url_does_not_infer_localhost_fallback(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@postgres.internal/app")
    monkeypatch.delenv("DATABASE_URL_FALLBACK", raising=False)
    monkeypatch.setattr("services.async_database.socket.getaddrinfo", Mock(side_effect=socket.gaierror()))

    assert _database_url() == "postgresql+asyncpg://user:pass@postgres.internal/app"


def test_database_preflight_retries_with_bounded_attempts(monkeypatch):
    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def exec_driver_sql(self, _sql):
            raise OSError("unreachable")

    class Engine:
        def __init__(self):
            self.connections = 0

        def connect(self):
            self.connections += 1
            return Connection()

    async def no_wait(_delay):
        return None

    monkeypatch.setenv("DATABASE_PREFLIGHT_ATTEMPTS", "3")
    monkeypatch.setattr("services.async_database.asyncio.sleep", no_wait)
    engine = Engine()

    try:
        asyncio.run(preflight_database(engine))
    except RuntimeError as exc:
        assert "after 3 attempts" in str(exc)
    else:
        raise AssertionError("Preflight should fail when all configured attempts fail")
    assert engine.connections == 3


def test_postgres_send_path_only_enqueues_outbox(monkeypatch):
    store = Mock()
    store.storage_engine = "postgresql"
    store.enqueue_outbox_message.return_value = {"id": "OUT-1", "status": "PENDING"}
    monkeypatch.setattr("services.communication_service.operations_store", store)
    monkeypatch.setattr("services.communication_service.send_message", Mock(side_effect=AssertionError("sent inline")))

    result = CommunicationService()._send(
        "sales", "buyer@example.test", "Quote", "Quote body", reply_to="message-1"
    )

    assert result["transmission_status"] == "PENDING"
    assert result["outbox_id"] == "OUT-1"
    store.enqueue_outbox_message.assert_called_once()


def test_outbox_dispatch_sends_only_after_claim_transaction_has_closed(monkeypatch):
    events = []

    class Store:
        storage_engine = "postgresql"

        def recover_stale_outbox_messages(self):
            events.append("recover")

        def claim_outbox_messages(self, *, limit):
            events.append("claim_commit")
            return [{
                "id": "OUT-1", "mailbox": "sales", "recipient": "buyer@example.test",
                "subject": "Quote", "payload": {"body": "Quote body"}, "reply_to": None,
            }]

        def transaction(self):
            class Tx:
                def __enter__(self):
                    events.append("db_transaction_begin")

                def __exit__(self, *_args):
                    events.append("db_transaction_end")
            return Tx()

        def record_communication(self, **_kwargs):
            events.append("record_communication")

        def mark_outbox_sent(self, _message_id):
            events.append("mark_sent")

        def fail_outbox_message(self, *_args):
            events.append("mark_failed")

    monkeypatch.setattr("services.communication_service.operations_store", Store())
    monkeypatch.setattr("services.communication_service.send_message", lambda *_args, **_kwargs: events.append("send"))
    result = CommunicationService().dispatch_outbox_once()

    assert result == {"sent": 1, "failed": 0}
    assert events.index("claim_commit") < events.index("send")
    assert events.index("send") < events.index("db_transaction_begin")
    assert events.index("mark_sent") < events.index("db_transaction_end")


def test_outbox_retries_only_explicit_provider_throttling(monkeypatch):
    class Store:
        storage_engine = "postgresql"

        def __init__(self):
            self.retryable = None

        def recover_stale_outbox_messages(self):
            return 0

        def claim_outbox_messages(self, *, limit):
            return [{"id": "OUT-1", "mailbox": "sales", "recipient": "buyer@example.test",
                     "subject": "Quote", "payload": {"body": "Body"}, "reply_to": None}]

        def fail_outbox_message(self, _message_id, _error, *, retryable=False):
            self.retryable = retryable
            return "PENDING" if retryable else "FAILED"

    throttled_store = Store()
    monkeypatch.setattr("services.communication_service.operations_store", throttled_store)
    monkeypatch.setattr("services.communication_service.send_message", Mock(side_effect=type("HttpError", (Exception,), {"response": SimpleNamespace(status_code=429)})()))
    CommunicationService().dispatch_outbox_once()
    assert throttled_store.retryable is True

    ambiguous_store = Store()
    monkeypatch.setattr("services.communication_service.operations_store", ambiguous_store)
    monkeypatch.setattr("services.communication_service.send_message", Mock(side_effect=TimeoutError("delivery outcome unknown")))
    CommunicationService().dispatch_outbox_once()
    assert ambiguous_store.retryable is False


def test_reconciliation_maps_legacy_ids_stably_and_conflict_policy_preserves_target():
    from scripts.reconcile_sqlite_to_postgres import assert_apply_has_complete_source, reconciliation_warnings, target_rows

    source = {
        "customers": [],
        "rfqs": [{"id": "RFQ-NORMALIZED", "customer_email": "buyer@example.test", "customer_name": "Buyer", "raw_text": "Part 123", "status": "Intake"}],
        "snapshot_rfqs": [], "rfq_items": [{"id": "ITEM-NORMALIZED", "rfq_id": "RFQ-NORMALIZED", "part_number": "123-45", "quantity": 2, "condition_code": "NE", "details": {"uom": "EA"}}], "snapshot_rfq_items": [],
        "customer_quotes": [{"id": "QUOTE-NORMALIZED", "rfq_id": "RFQ-NORMALIZED", "status": "Draft", "total_amount": 50}],
        "snapshot_quotes": [], "customer_quote_items": [{"id": "QI-NORMALIZED", "quote_id": "QUOTE-NORMALIZED", "part_number": "123-45", "quantity": 2, "unit_price": 25, "details": {"certification": "CoC"}}], "snapshot_quote_items": [],
        "suppliers": [{"id": "SUP-1", "company_name": "Supplier", "email": "supplier@example.test", "approval_status": "Approved"}],
        "supplier_parts": [{"id": "PART-1", "supplier_id": "SUP-1", "part_number": "060-1234-00", "source_email_id": "message-id-1"}],
        "snapshot_suppliers": [{"id": "SUP-MODEL-1", "company_name": "Supplier Model", "contact_name": "Contact"}],
        "snapshot_audit_logs": [
            {"id": 1, "rfq_id": "RFQ-A", "agent_name": "Agent", "action_type": "parse", "message": "A"},
            {"id": 1, "rfq_id": "RFQ-B", "agent_name": "Agent", "action_type": "parse", "message": "B"},
        ], "communications": [], "inbound_emails": [], "communication_tasks": [],
        "snapshot_inventory": [], "snapshot_shipments": [], "snapshot_shipment_events": [],
    }
    first = target_rows(source)
    second = target_rows(source)

    assert first["supplier_parts"][0]["id"] == second["supplier_parts"][0]["id"]
    assert first["supplier_parts"][0]["supplier_id"] == "SUP-1"
    assert len({row["id"] for row in first["audit_events"]}) == 2
    records = {(row["domain"], row["record_id"]): row["payload"] for row in first["operational_records"]}
    assert {"suppliers", "rfqs", "rfq_items", "quotes", "quote_items"} <= {domain for domain, _record_id in records}
    assert records[("rfqs", "RFQ-NORMALIZED")]["customer_email"] == "buyer@example.test"
    assert records[("quotes", "QUOTE-NORMALIZED")]["total_amount"] == 50
    warnings = reconciliation_warnings(source)
    assert any(item["table"] == "customer_quote_items" and item["severity"] == "blocking" for item in warnings)
    try:
        assert_apply_has_complete_source(warnings)
    except RuntimeError as exc:
        assert "incomplete source data" in str(exc)
    else:
        raise AssertionError("Incomplete quote data must prevent reconciliation apply")
    assert "on_conflict_do_nothing" in Path("scripts/reconcile_sqlite_to_postgres.py").read_text(encoding="utf-8")