import os
import sqlite3
import unittest
from unittest.mock import patch

from api import auth


class TestPrivacyPolicyAcceptance(unittest.TestCase):
    def setUp(self):
        self.test_db_path = "data/test_auth_privacy.db"
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
        self.auth_patcher = patch.object(auth, "AUTH_DB_PATH", self.test_db_path)
        self.auth_patcher.start()
        auth.init_auth_db()

    def tearDown(self):
        self.auth_patcher.stop()
        if os.path.exists(self.test_db_path):
            try:
                os.remove(self.test_db_path)
            except OSError:
                pass

    def test_first_time_customer_login_requires_privacy_policy(self):
        email = "airline.buyer@globalairways.com"
        challenge_id, code = auth.request_otp(email, auth.ROLE_CUSTOMER, "Global Airways Procurement")

        result = auth.verify_otp(challenge_id, code)
        self.assertEqual(result["email"], email)
        self.assertEqual(result["role"], auth.ROLE_CUSTOMER)
        self.assertFalse(result["privacy_policy_accepted"], "First-time sign-in must not have privacy policy accepted")

        # Check status before acceptance
        with auth._connect() as conn:
            user = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            user_id = user["id"]

        status_before = auth.get_privacy_policy_status(user_id)
        self.assertFalse(status_before["privacy_policy_accepted"])
        self.assertIsNone(status_before["privacy_policy_accepted_at"])

        # Accept the privacy policy
        accepted_at = auth.record_privacy_policy_acceptance(user_id)
        self.assertTrue(bool(accepted_at))

        # Check status after acceptance
        status_after = auth.get_privacy_policy_status(user_id)
        self.assertTrue(status_after["privacy_policy_accepted"])
        self.assertEqual(status_after["privacy_policy_accepted_at"], accepted_at)

        # Verify audit event was logged
        with auth._connect() as conn:
            audit = conn.execute(
                "SELECT * FROM audit_events WHERE user_id = ? AND action = ?",
                (user_id, "privacy_policy_accepted"),
            ).fetchone()
            self.assertIsNotNone(audit)
            self.assertEqual(audit["metadata"], "v1.0")

        # Second login should recognize that policy was already accepted
        challenge_id_2, code_2 = auth.request_otp(email, auth.ROLE_CUSTOMER, "Global Airways Procurement")
        result_2 = auth.verify_otp(challenge_id_2, code_2)
        self.assertTrue(result_2["privacy_policy_accepted"], "Subsequent login must reflect accepted privacy policy")


if __name__ == "__main__":
    unittest.main()
