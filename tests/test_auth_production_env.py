import os
import sqlite3
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.auth import request_otp
from api.main import app


class ProductionAuthConfigTests(unittest.TestCase):
    def setUp(self):
        self.original_env = os.environ.get("WT_AUTH_ENV")
        self.original_secret = os.environ.get("WT_AUTH_SECRET")
        self.db_path = os.getenv("WT_AUTH_DB", "data/winged_tycoons_auth.db")
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("DELETE FROM otp_challenges")
            connection.execute("DELETE FROM sessions")
            connection.execute("DELETE FROM audit_events")
            connection.execute("DELETE FROM users WHERE email LIKE '%@wingedtycoons.com%'")
            connection.execute(
                "INSERT INTO users (id, email, full_name, role, is_email_verified, is_active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("INT-TEST-1", "camila@wingedtycoons.com", "Camila", "ROLE_ADMIN", 1, 1, "2026-01-01T00:00:00Z"),
            )
            connection.execute(
                "INSERT INTO users (id, email, full_name, role, is_email_verified, is_active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("INT-TEST-2", "camila+prod2@wingedtycoons.com", "Camila 2", "ROLE_ADMIN", 1, 1, "2026-01-01T00:00:00Z"),
            )
            connection.commit()
        finally:
            connection.close()

    def tearDown(self):
        if self.original_env is None:
            os.environ.pop("WT_AUTH_ENV", None)
        else:
            os.environ["WT_AUTH_ENV"] = self.original_env

        if self.original_secret is None:
            os.environ.pop("WT_AUTH_SECRET", None)
        else:
            os.environ["WT_AUTH_SECRET"] = self.original_secret

    def test_production_mode_never_returns_plaintext_otp(self):
        with patch.dict(os.environ, {"WT_AUTH_ENV": "production", "WT_AUTH_SECRET": "test-secret"}, clear=False):
            with patch("api.main.send_otp_email") as mock_send_email:
                client = TestClient(app)
                response = client.post(
                    "/api/auth/otp/request",
                    json={"email": "camila+prod1@wingedtycoons.com", "role": "ROLE_ADMIN", "full_name": "Camila"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("development_otp", response.json())
                self.assertEqual(mock_send_email.call_count, 1)

    def test_production_verify_sets_secure_cookie(self):
        with patch.dict(os.environ, {"WT_AUTH_ENV": "production", "WT_AUTH_SECRET": "test-secret"}, clear=False):
            with patch("api.main.send_otp_email"):
                client = TestClient(app)
                challenge_id, code = request_otp("camila+prod2@wingedtycoons.com", "ROLE_INTERNAL", "Camila")
                response = client.post(
                    "/api/auth/otp/verify",
                    json={"challenge_id": challenge_id, "code": code},
                )
                self.assertEqual(response.status_code, 200)
                set_cookie = response.headers.get("set-cookie", "")
                self.assertIn("wt_session=", set_cookie)
                self.assertIn("Secure", set_cookie)
                self.assertIn("SameSite=Strict", set_cookie)


if __name__ == "__main__":
    unittest.main()
