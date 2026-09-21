import tempfile
import unittest
from pathlib import Path

from services.operations_store import OperationsStore


class TestOperationsTransaction(unittest.TestCase):
    def test_failed_transaction_rolls_back_without_partial_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OperationsStore(Path(directory) / "operations.db")
            store.save({"status": "before"})
            with self.assertRaisesRegex(RuntimeError, "rollback"):
                with store.transaction() as connection:
                    connection.execute("UPDATE operations_state SET payload = ? WHERE state_key = 'current'", ('{"status":"partial"}',))
                    raise RuntimeError("rollback")

            self.assertEqual(store.load(), {"status": "before"})


if __name__ == "__main__":
    unittest.main()