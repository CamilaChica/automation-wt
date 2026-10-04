import asyncio
import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException

from api.partsbase_routes import PartsBaseQuoteRequest, request_partsbase_quote
from models.db_models import RFQItem


class TestPartsBaseRoutes(unittest.TestCase):
    def test_manual_request_infers_exact_quantity_from_matching_rfq_item(self):
        item = RFQItem(
            id="ITEM-1",
            rfq_id="RFQ-1",
            requested_part_number="ABC123",
            quantity=6,
        )
        job = {"job_id": "JOB-1", "status": "queued"}
        with (
            patch("api.partsbase_routes.db_service.get_rfq_items", return_value=[item]),
            patch("api.partsbase_routes.partsbase_service.credentials_configured", return_value=True),
            patch("api.partsbase_routes.partsbase_service.start_job", return_value=job) as start_job,
        ):
            response = asyncio.run(request_partsbase_quote(
                "RFQ-1",
                PartsBaseQuoteRequest(part_numbers="abc123"),
                BackgroundTasks(),
                {"email": "buyer@wingedtycoons.com"},
            ))

        self.assertEqual(response, job)
        start_job.assert_called_once_with(
            "RFQ-1",
            ["ABC123"],
            {"ABC123": 6},
            "buyer@wingedtycoons.com",
        )

    def test_manual_request_rejects_part_without_known_requested_quantity(self):
        with patch("api.partsbase_routes.db_service.get_rfq_items", return_value=[]):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(request_partsbase_quote(
                    "RFQ-1",
                    PartsBaseQuoteRequest(part_numbers="UNKNOWN"),
                    BackgroundTasks(),
                    {"email": "buyer@wingedtycoons.com"},
                ))

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("Provide a quantity", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
