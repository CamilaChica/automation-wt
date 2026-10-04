from __future__ import annotations

import asyncio
import base64
import socket
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

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


def test_customer_quote_enqueue_does_not_advance_quote_or_rfq_before_delivery(monkeypatch):
    store = MagicMock()
    store.storage_engine = "postgresql"
    store.enqueue_outbox_message.return_value = {"id": "OUT-QUOTE-1", "status": "PENDING"}
    quote = SimpleNamespace(id="QUOTE-1", rfq_id="RFQ-1", lead_time_days=2, valid_until="2026-10-29")
    rfq = SimpleNamespace(id="RFQ-1", customer_name="Buyer", customer_email="buyer@example.test", thread_id=None)
    quote_status = Mock()
    rfq_status = Mock()
    monkeypatch.setattr("services.communication_service.operations_store", store)
    monkeypatch.setattr("services.communication_service.db_service.get_quote", Mock(return_value=quote))
    monkeypatch.setattr("services.communication_service.db_service.get_quote_items", Mock(return_value=[]))
    monkeypatch.setattr("services.communication_service.db_service.get_rfq", Mock(return_value=rfq))
    monkeypatch.setattr("services.communication_service.db_service.get_rfq_items", Mock(return_value=[]))
    monkeypatch.setattr("services.communication_service.db_service.update_quote_status", quote_status)
    monkeypatch.setattr("services.communication_service.db_service.update_rfq_status", rfq_status)
    monkeypatch.setattr("services.communication_service.prepare_and_validate_email", Mock(return_value=True))
    monkeypatch.setattr(CommunicationService, "schedule_customer_followup", Mock())

    result = CommunicationService().send_customer_quote(
        recipient="buyer@example.test",
        customer_name="Buyer",
        quote_id="QUOTE-1",
        quote_summary="Quote total: $100.00",
    )

    assert result["transmission_status"] == "PENDING"
    quote_status.assert_not_called()
    rfq_status.assert_not_called()


def test_sent_outbox_finalization_advances_quote_and_rfq(monkeypatch):
    store = MagicMock()
    store.storage_engine = "postgresql"
    store.claim_outbox_messages.return_value = [{
        "id": "OUT-QUOTE-1", "mailbox": "sales", "recipient": "buyer@example.test",
        "subject": "Quote", "payload": {"body": "Approved quote"}, "reply_to": None,
        "entity_id": "QUOTE-1",
    }]
    quote = SimpleNamespace(id="QUOTE-1", rfq_id="RFQ-1", status="Approved")
    rfq = SimpleNamespace(id="RFQ-1", status="Pending_Approval")
    quote_transitions = []
    rfq_transitions = []
    monkeypatch.setattr("services.communication_service.operations_store", store)
    monkeypatch.setattr("services.communication_service.db_service.get_quote", Mock(return_value=quote))
    monkeypatch.setattr("services.communication_service.db_service.get_rfq", Mock(return_value=rfq))
    monkeypatch.setattr(
        "services.communication_service.db_service.update_quote_status",
        lambda _quote_id, status: quote_transitions.append(status),
    )
    monkeypatch.setattr(
        "services.communication_service.db_service.update_rfq_status",
        lambda _rfq_id, status: rfq_transitions.append(status),
    )
    monkeypatch.setattr("services.communication_service.send_message", Mock())

    result = CommunicationService().dispatch_outbox_once()

    assert result == {"sent": 1, "failed": 0}
    assert quote_transitions == ["Sent"]
    assert rfq_transitions == ["Quote_Sent"]
    store.mark_outbox_sent.assert_called_once_with("OUT-QUOTE-1")


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


def test_outbox_dispatch_decodes_and_sends_queued_attachments(monkeypatch):
    store = MagicMock()
    store.storage_engine = "postgresql"
    store.claim_outbox_messages.return_value = [{
        "id": "OUT-PO-ATTACHMENT",
        "mailbox": "sales",
        "recipient": "camila@wingedtycoons.com",
        "subject": "PO received",
        "payload": {
            "body": "Please review the attached PO.",
            "attachments": [{
                "filename": "purchase-order.pdf",
                "content_type": "application/pdf",
                "content_base64": base64.b64encode(b"%PDF-test").decode("ascii"),
            }],
        },
        "reply_to": None,
        "entity_id": None,
    }]
    store.transaction.return_value = nullcontext()
    send = Mock(return_value=True)
    monkeypatch.setattr("services.communication_service.operations_store", store)
    monkeypatch.setattr("services.communication_service.send_message", send)

    result = CommunicationService().dispatch_outbox_once()

    assert result == {"sent": 1, "failed": 0}
    send.assert_called_once()
    assert send.call_args.kwargs["attachments"] == [{
        "filename": "purchase-order.pdf",
        "content_type": "application/pdf",
        "content": b"%PDF-test",
    }]


def test_outbox_retries_throttling_and_server_errors_but_quarantines_timeouts(monkeypatch):
    class Store:
        storage_engine = "postgresql"

        def __init__(self):
            self.retryable = None
            self.delivery_state = None

        def recover_stale_outbox_messages(self):
            return 0

        def claim_outbox_messages(self, *, limit):
            return [{"id": "OUT-1", "mailbox": "sales", "recipient": "buyer@example.test",
                     "subject": "Quote", "payload": {"body": "Body"}, "reply_to": None,
                     "entity_id": "QUOTE-1"}]

        def fail_outbox_message(self, _message_id, _error, *, retryable=False):
            self.retryable = retryable
            self.delivery_state = "PENDING" if retryable else "MANUAL_REVIEW_REQUIRED"
            return self.delivery_state

        def update_customer_quote_status(self, _quote_id, _status):
            return None

        def cancel_communication_task(self, _task_key):
            return None

    throttled_store = Store()
    monkeypatch.setattr("services.communication_service.operations_store", throttled_store)
    monkeypatch.setattr("services.communication_service.send_message", Mock(side_effect=type("HttpError", (Exception,), {"response": SimpleNamespace(status_code=429)})()))
    CommunicationService().dispatch_outbox_once()
    assert throttled_store.retryable is True

    ambiguous_store = Store()
    monkeypatch.setattr("services.communication_service.operations_store", ambiguous_store)
    monkeypatch.setattr("services.communication_service.db_service.get_quote", lambda _quote_id: SimpleNamespace(
        id="QUOTE-1", rfq_id="RFQ-1", status="Approved"
    ))
    monkeypatch.setattr("services.communication_service.db_service.get_rfq", lambda _rfq_id: SimpleNamespace(
        id="RFQ-1", status="Pending_Approval"
    ))
    quote_transitions = []
    rfq_transitions = []
    monkeypatch.setattr("services.communication_service.db_service.update_quote_status", lambda _quote_id, status: quote_transitions.append(status))
    monkeypatch.setattr("services.communication_service.db_service.update_rfq_status", lambda _rfq_id, status: rfq_transitions.append(status))
    monkeypatch.setattr("services.communication_service.send_message", Mock(side_effect=TimeoutError("delivery outcome unknown")))
    CommunicationService().dispatch_outbox_once()
    assert ambiguous_store.retryable is False
    assert ambiguous_store.delivery_state == "MANUAL_REVIEW_REQUIRED"
    assert quote_transitions == ["Pending_Internal_Review"]
    assert rfq_transitions == ["Pending_Internal_Review"]

    server_error_store = Store()
    monkeypatch.setattr("services.communication_service.operations_store", server_error_store)
    monkeypatch.setattr(
        "services.communication_service.send_message",
        Mock(side_effect=type("HttpError", (Exception,), {"response": SimpleNamespace(status_code=503)})()),
    )
    CommunicationService().dispatch_outbox_once()
    assert server_error_store.retryable is True
    assert server_error_store.delivery_state == "PENDING"


def test_reconciliation_maps_legacy_ids_stably_and_conflict_policy_preserves_target():
    from scripts.reconcile_sqlite_to_postgres import (
        assert_apply_has_complete_source,
        assert_reconciliation_safe,
        assert_disposition_approval,
        reconciliation_warnings,
        target_rows,
    )

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
    target_supplier = [{"id": "SUP-TARGET", "email": "supplier@example.test"}]
    first = target_rows(source, target_suppliers=target_supplier)
    second = target_rows(source, target_suppliers=target_supplier)

    assert first["supplier_parts"][0]["id"] == second["supplier_parts"][0]["id"]
    assert first["supplier_parts"][0]["supplier_id"] == "SUP-TARGET"
    assert not any(row["id"] == "SUP-TARGET" for row in first["suppliers"])
    assert first["quarantine_supplier_profiles"][0]["matched_supplier_id"] == "SUP-TARGET"
    assert len({row["id"] for row in first["audit_events"]}) == 2
    records = {(row["domain"], row["record_id"]): row["payload"] for row in first["operational_records"]}
    assert {"suppliers", "rfqs", "rfq_items", "quotes"} <= {domain for domain, _record_id in records}
    assert records[("rfqs", "RFQ-NORMALIZED")]["customer_email"] == "buyer@example.test"
    assert records[("quotes", "QUOTE-NORMALIZED")]["total_amount"] == 50
    warnings = reconciliation_warnings(source)
    assert any(item["table"] == "customer_quote_items" and item["severity"] == "review" for item in warnings)
    assert any(item["table"] == "suppliers" and item["severity"] == "review" for item in warnings)
    assert records[("rfqs", "RFQ-NORMALIZED")]["status"] == "Pending_Internal_Review"
    assert records[("quotes", "QUOTE-NORMALIZED")]["status"] == "Pending_Internal_Review"
    incomplete_item = records[("quote_items", "QI-NORMALIZED")]
    assert incomplete_item["source"] == "Legacy"
    assert incomplete_item["unit_cost"] == 0.0
    assert incomplete_item["margin_percent"] == 0.0
    assert incomplete_item["compliance_status"] == "Needs_Review"
    assert incomplete_item["reconciliation_review_required"] is True
    assert len(first["operator_review_queue"]) == 2
    try:
        assert_apply_has_complete_source([{"severity": "blocking", "table": "unknown", "count": 1}])
    except RuntimeError as exc:
        assert "incomplete source data" in str(exc)
    else:
        raise AssertionError("Incomplete quote data must prevent reconciliation apply")
    assert_reconciliation_safe(target_key_collisions=0, schema_truncations=0, foreign_key_violations=0)
    for failures in (
        {"target_key_collisions": 1, "schema_truncations": 0, "foreign_key_violations": 0},
        {"target_key_collisions": 0, "schema_truncations": 1, "foreign_key_violations": 0},
        {"target_key_collisions": 0, "schema_truncations": 0, "foreign_key_violations": 1},
    ):
        try:
            assert_reconciliation_safe(**failures)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"Unsafe reconciliation was allowed: {failures}")
    review_warnings = [{"severity": "review", "table": "suppliers", "count": 1}]
    for approved, reference in ((False, "REL-123"), (True, ""), (True, "secret value")):
        try:
            assert_disposition_approval(
                review_warnings, approved=approved, approval_reference=reference
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("Review-bearing apply must require explicit approval and a sanitized reference")
    assert_disposition_approval(
        review_warnings, approved=True, approval_reference="REL-123"
    )


def test_reconciliation_quarantines_orphan_quote_items_and_skips_exact_duplicates():
    from scripts.reconcile_sqlite_to_postgres import target_rows

    source = {
        "customers": [],
        "rfqs": [{"id": "RFQ-VALID", "customer_email": "buyer@example.test", "customer_name": "Buyer"}],
        "snapshot_rfqs": [], "rfq_items": [], "snapshot_rfq_items": [],
        "customer_quotes": [
            {"id": "QUOTE-VALID", "rfq_id": "RFQ-VALID", "total_amount": 20},
            {"id": "QUOTE-ORPHAN", "rfq_id": "RFQ-MISSING", "total_amount": 10},
        ],
        "snapshot_quotes": [], "snapshot_quote_items": [],
        "customer_quote_items": [
            {"id": "QI-1", "quote_id": "QUOTE-VALID", "part_number": "PN-1", "description": "Part", "quantity": 1, "unit_price": 20},
            {"id": "QI-2", "quote_id": "QUOTE-VALID", "part_number": "PN-1", "description": "Part", "quantity": 1, "unit_price": 20},
            {"id": "QI-3", "quote_id": "QUOTE-VALID", "part_number": "PN-1", "description": "Part", "quantity": 1, "unit_price": 20, "details": {"unit_cost": 12}},
            {"id": "QI-ORPHAN", "quote_id": "QUOTE-ORPHAN", "part_number": "PN-2", "quantity": 1, "unit_price": 10},
        ],
        "suppliers": [], "snapshot_suppliers": [], "supplier_parts": [],
        "snapshot_audit_logs": [], "communications": [], "inbound_emails": [],
        "communication_tasks": [], "snapshot_inventory": [], "snapshot_shipments": [],
        "snapshot_shipment_events": [],
    }

    mapped = target_rows(source)
    records = {(row["domain"], row["record_id"]): row["payload"] for row in mapped["operational_records"]}

    assert ("quote_items", "QI-1") in records
    assert ("quote_items", "QI-2") not in records
    assert ("quote_items", "QI-3") in records
    assert len(mapped["quarantine_quote_items"]) == 1
    assert mapped["quarantine_quote_items"][0]["source_id"] == "QI-ORPHAN"
    assert mapped["quarantine_quote_items"][0]["is_active"] is False
    assert mapped["_reconciliation"]["skipped_duplicate_line_items"] == 1


def test_reconciliation_supplier_match_preserves_target_and_quarantines_unmatched_offer():
    from scripts.reconcile_sqlite_to_postgres import target_rows

    source = {
        "customers": [], "rfqs": [], "snapshot_rfqs": [], "rfq_items": [], "snapshot_rfq_items": [],
        "customer_quotes": [], "snapshot_quotes": [], "customer_quote_items": [], "snapshot_quote_items": [],
        "suppliers": [{"id": "SUP-MATCH", "company_name": "Supplier", "email": "quotes@acme.example", "tax_id": "12-345"}],
        "snapshot_suppliers": [{"id": "SUP-MATCH", "company_name": "Supplier", "email": "quotes@acme.example", "tax_id": "12-345", "contact_name": "Buyer", "address_line1": "1 Main"}],
        "supplier_parts": [{"id": "PART-1", "supplier_id": "SUP-MATCH", "supplier_name": "Supplier", "supplier_email": "quotes@acme.example", "part_number": "PN-1"},
                           {"id": "PART-2", "supplier_id": "SUP-UNKNOWN", "supplier_name": "Unknown", "supplier_email": "unknown@vendor.example", "part_number": "PN-2"}],
        "snapshot_audit_logs": [], "communications": [], "inbound_emails": [], "communication_tasks": [],
        "snapshot_inventory": [], "snapshot_shipments": [], "snapshot_shipment_events": [],
    }

    mapped = target_rows(source, target_suppliers=[{"id": "LIVE-SUP", "email": "ap@acme.example", "tax_id": "12345"}])
    supplier_records = {(row["domain"], row["record_id"]) for row in mapped["operational_records"] if row["domain"] == "suppliers"}

    assert not any(row["id"] == "LIVE-SUP" for row in mapped["suppliers"])
    assert ("suppliers", "LIVE-SUP") not in supplier_records
    assert mapped["supplier_parts"][0]["supplier_id"] == "LIVE-SUP"
    assert len(mapped["quarantine_supplier_profiles"]) == 1
    quarantine = mapped["quarantine_supplier_profiles"][0]
    assert quarantine["source_id"] == "SUP-UNKNOWN"
    assert quarantine["is_active"] is False
    assert quarantine["payload"]["related_supplier_parts"][0]["id"] == "PART-2"


def test_reconciliation_preflight_reports_schema_collisions_and_foreign_keys():
    from sqlalchemy import MetaData, create_engine, text

    from scripts.reconcile_sqlite_to_postgres import (
        foreign_key_violations,
        schema_truncation_warnings,
        target_key_collisions,
    )

    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE parents (id VARCHAR(4) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO parents (id) VALUES ('P1')"))
        connection.execute(text("CREATE TABLE children (id VARCHAR(8) PRIMARY KEY, parent_id VARCHAR(4) REFERENCES parents(id))"))
        metadata = MetaData()
        rows = {
            "parents": [{"id": "P1"}, {"id": "PARENT-LONG", "unmapped": "value"}],
            "children": [{"id": "C1", "parent_id": "MISSING"}],
        }

        assert len(schema_truncation_warnings(connection, metadata, rows)) == 3
        assert sum(item["count"] for item in target_key_collisions(connection, metadata, rows)) == 1
        assert sum(item["count"] for item in foreign_key_violations(connection, metadata, rows)) == 1
    engine.dispose()


def test_reconciliation_dry_run_transaction_rolls_back_and_apply_commits():
    from scripts.reconcile_sqlite_to_postgres import finish_transaction

    class Transaction:
        committed = False
        rolled_back = False

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

    dry_run = Transaction()
    apply = Transaction()

    assert finish_transaction(dry_run, apply=False) == "rolled_back"
    assert dry_run.rolled_back and not dry_run.committed
    assert finish_transaction(apply, apply=True) == "committed"
    assert apply.committed and not apply.rolled_back


def test_historical_reconciliation_entrypoint_is_disabled():
    from scripts.reconcile_sqlite_to_postgres import reconcile

    try:
        reconcile(Path("unused"), apply=True, url="postgresql://unused")
    except RuntimeError as exc:
        assert "Historical SQLite-to-PostgreSQL reconciliation is canceled" in str(exc)
    else:
        raise AssertionError("Canceled historical reconciliation must not connect or write")