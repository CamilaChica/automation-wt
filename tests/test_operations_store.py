import tempfile
import unittest
from pathlib import Path

from services.operations_store import OperationsStore


class TestOperationsStore(unittest.TestCase):
    def test_state_survives_store_reinitialization(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operations.db"
            first = OperationsStore(path)
            first.save({"rfq_id": "RFQ-123", "status": "Pending_Approval", "items": ["060-1234-00"]})

            second = OperationsStore(path)

            self.assertEqual(second.load(), {
                "rfq_id": "RFQ-123",
                "status": "Pending_Approval",
                "items": ["060-1234-00"],
            })


if __name__ == "__main__":
    unittest.main()
