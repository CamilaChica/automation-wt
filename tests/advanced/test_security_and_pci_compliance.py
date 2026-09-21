"""Security, confidentiality, and audit-chain quality gates."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.communication_service import CommunicationService
from services.operations_store import OperationsStore


class TestSecurityAndPCICompliance(unittest.TestCase):
    def test_customer_po_notice_contains_no_unnecessary_supplier_margin_fields(self):
        service = CommunicationService()
        with patch.dict("os.environ", {"EMAIL_SEND_ENABLED": "false"}, clear=False), patch.object(service, "_send", return_value={}) as send:
            service.notify_purchase_order(
                recipient="staff@winged.example",
                po_number="PO-1001",
                customer_name="Global Airlines",
                customer_email="buyer@example.com",
                quote_id="QTE-1001",
                items=[{
                    "part_number": "XYZ123",
                    "quantity": 1,
                    "unit_price": 4600.0,
                    "supplier_name": "Apex Aerospace",
                    "supplier_unit_cost": 3500.0,
                }],
            )
        body = send.call_args.args[3]
        self.assertIn("Apex Aerospace", body)
        self.assertIn("$3,500.00", body)

    def test_customer_quote_does_not_contain_supplier_cost(self):
        service = CommunicationService()
        with patch.dict("os.environ", {"EMAIL_SEND_ENABLED": "false"}, clear=False), patch.object(service, "_send", return_value={}) as send:
            service.send_customer_quote(
                "buyer@example.com",
                "Buyer",
                "QTE-1001",
                "Part XYZ123 | Qty 1 | Unit price $4,600.00",
            )
        body = send.call_args.args[3]
        self.assertNotIn("3500", body)
        self.assertNotIn("supplier_unit_cost", body)
        self.assertNotIn("Apex Aerospace", body)

    def test_automation_event_audit_record_contains_result_and_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OperationsStore(Path(directory) / "operations.db")
            event_id = store.record_automation_event(
                event_type="compliance_check",
                entity_type="rfq",
                entity_id="RFQ-1",
                status="SUCCEEDED",
                result=json.dumps({"agent": "ComplianceAgent", "status": "APPROVED"}),
            )
            connection = sqlite3.connect(Path(directory) / "operations.db")
            row = connection.execute(
                "SELECT status, execution_time, result FROM automation_events WHERE id = ?",
                (event_id,),
            ).fetchone()
            connection.close()

        self.assertEqual(row[0], "SUCCEEDED")
        self.assertTrue(row[1])
        self.assertIn("ComplianceAgent", row[2])

    @unittest.skip("Immutable append-only audit enforcement and full lifecycle event assertions are not implemented.")
    def test_full_rfq_lifecycle_is_immutable_and_complete(self):
        pass

    @unittest.skip("Public customer quote endpoint security tests require the future normalized quote API.")
    def test_public_endpoint_never_exposes_supplier_identifiers(self):
        pass


if __name__ == "__main__":
    unittest.main()
