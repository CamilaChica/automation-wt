import os
import unittest
from unittest.mock import patch

from services.freight_service import FreightRateService


class TestFreightRateService(unittest.TestCase):
    def test_defaults_to_dry_run_without_adding_shipping(self):
        with patch.dict(os.environ, {}, clear=True):
            result = FreightRateService().quote(
                origin="Miami, FL",
                destination="Dallas, TX",
                weight_kg=12.5,
            )

        self.assertEqual(result["status"], "DRY_RUN")
        self.assertEqual(result["rates"], [])
        self.assertIn("not added", result["message"])

    def test_normalizes_and_sorts_provider_rates(self):
        response = type("Response", (), {
            "json": lambda self: {
                "rates": [
                    {"service": "Express", "amount": 240, "currency": "USD", "estimated_days": 2},
                    {"service": "Standard", "amount": 80, "currency": "USD", "estimated_days": 5},
                    {"service": "Invalid", "amount": None},
                ]
            },
            "raise_for_status": lambda self: None,
        })()
        environment = {
            "FREIGHT_ENABLED": "true",
            "FREIGHT_API_BASE_URL": "https://freight.example.test",
            "FREIGHT_API_KEY": "freight-secret",
        }
        with patch.dict(os.environ, environment, clear=True), patch("services.freight_service.requests.post", return_value=response) as post:
            result = FreightRateService().quote(
                origin="Miami, FL",
                destination="Dallas, TX",
                weight_kg=12.5,
            )

        self.assertEqual(result["status"], "QUOTED")
        self.assertEqual(result["rates"][0]["service"], "Standard")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer freight-secret")

    def test_rejects_invalid_weight(self):
        with self.assertRaises(ValueError):
            FreightRateService().quote(origin="Miami", destination="Dallas", weight_kg=0)


if __name__ == "__main__":
    unittest.main()
