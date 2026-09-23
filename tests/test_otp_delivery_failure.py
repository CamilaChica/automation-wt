import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app


class TestOtpDeliveryFailure(unittest.TestCase):
    def test_production_mail_failure_returns_recoverable_503(self):
        with patch.dict(os.environ, {"WT_AUTH_ENV": "production"}, clear=False), patch(
            "api.main.request_otp", return_value=("challenge-test", "123456")
        ), patch("api.main.send_otp_email", side_effect=RuntimeError("Graph sendMail denied")):
            response = TestClient(app).post(
                "/api/auth/otp/request",
                json={"email": "buyer@example.com", "role": "ROLE_CUSTOMER"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("verification email service", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
