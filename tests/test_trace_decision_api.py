import unittest

from fastapi.testclient import TestClient

from api.auth import current_user
from api.main import app
from services.db_service import db_service


class TestTraceDecisionApi(unittest.TestCase):
    def test_freeze_persists_audit_and_pauses_rfq(self):
        rfq = db_service.create_rfq("Trace Customer", "trace@example.com", "P/N 060-1234-00 qty 1")
        app.dependency_overrides[current_user] = lambda: {
            "role": "ROLE_ADMIN",
            "email": "operator@example.com",
        }
        try:
            response = TestClient(app).post(
                f"/api/internal/rfqs/{rfq.id}/trace-decision",
                json={"decision": "freeze", "reason": "Trace gap requires review."},
            )
        finally:
            app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["automation_paused"])
        self.assertTrue(db_service.get_rfq(rfq.id).automation_paused)
        self.assertTrue(any(log.action_type == "trace_freeze" for log in db_service.get_audit_logs(rfq.id)))


if __name__ == "__main__":
    unittest.main()
