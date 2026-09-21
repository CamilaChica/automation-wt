import tempfile
import unittest
from pathlib import Path

from models.db_models import RFQ
from services.operations_store import OperationsStore
from services.workflow_states import WorkflowState, canonical_state, validate_transition


class TestWorkflowStates(unittest.TestCase):
    def test_legacy_status_maps_to_canonical_state(self):
        self.assertEqual(canonical_state("Supplier_Sourcing"), WorkflowState.SOURCING_SUPPLIERS)
        self.assertEqual(canonical_state("Quote_Sent"), WorkflowState.QUOTE_SENT)

    def test_invalid_transition_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_transition("Intake", "Quote_Sent")

    def test_restored_rfq_can_carry_canonical_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OperationsStore(Path(directory) / "operations.db")
            store.save({
                "rfqs": {
                    "RFQ-1": {
                        "id": "RFQ-1",
                        "customer_name": "Test Buyer",
                        "customer_email": "buyer@example.com",
                        "status": "Supplier_Sourcing",
                        "raw_text": "Need one part",
                    }
                }
            })
            restored = store.load()["rfqs"]["RFQ-1"]

        self.assertEqual(restored["status"], "Supplier_Sourcing")
        self.assertEqual(canonical_state(restored["status"]), WorkflowState.SOURCING_SUPPLIERS)


if __name__ == "__main__":
    unittest.main()
