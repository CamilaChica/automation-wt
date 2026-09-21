import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.automation_queue import AutomationQueue
from services.operations_store import OperationsStore


class TestAutomationQueue(unittest.TestCase):
    def test_handler_success_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OperationsStore(Path(directory) / "operations.db")
            queue = AutomationQueue()
            queue.register("predictive_check", lambda: {"risk": "LOW"})
            with patch("services.automation_queue.operations_store", store):
                event_id = asyncio.run(queue.enqueue(
                    event_type="predictive_check",
                    entity_type="part",
                    entity_id="060-1234-00",
                    idempotency_key="predictive:060-1234-00",
                ))
                event = queue._event(event_id)

        self.assertEqual(event["status"], "SUCCEEDED")
        self.assertEqual(event["attempts"], 1)

    def test_handler_retries_then_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OperationsStore(Path(directory) / "operations.db")
            queue = AutomationQueue()
            calls = 0

            def flaky_handler():
                nonlocal calls
                calls += 1
                if calls < 2:
                    raise RuntimeError("temporary provider error")
                return {"ok": True}

            queue.register("flaky", flaky_handler)
            with patch("services.automation_queue.operations_store", store):
                event_id = asyncio.run(queue.enqueue(
                    event_type="flaky",
                    entity_type="rfq",
                    entity_id="RFQ-1",
                    idempotency_key="flaky:RFQ-1",
                ))
                event = queue._event(event_id)

        self.assertEqual(event["status"], "SUCCEEDED")
        self.assertEqual(event["attempts"], 2)

    def test_duplicate_idempotency_key_reuses_event(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OperationsStore(Path(directory) / "operations.db")
            queue = AutomationQueue()
            executions = 0

            def handler():
                nonlocal executions
                executions += 1
                return {"ok": True}

            queue.register("once", handler)
            with patch("services.automation_queue.operations_store", store):
                first = asyncio.run(queue.enqueue(
                    event_type="once", entity_type="rfq", entity_id="RFQ-1", idempotency_key="once:RFQ-1"
                ))
                second = asyncio.run(queue.enqueue(
                    event_type="once", entity_type="rfq", entity_id="RFQ-1", idempotency_key="once:RFQ-1"
                ))

        self.assertEqual(first, second)
        self.assertEqual(executions, 1)


if __name__ == "__main__":
    unittest.main()
