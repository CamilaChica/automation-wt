import unittest
import uuid
import sqlite3
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from api.main import app
from services.stock_reservation_service import StockReservationService
from services.client_history_service import ClientHistoryService


class TestStockReservation(unittest.TestCase):
    def setUp(self):
        self.test_db = f"data/test_stock_res_{uuid.uuid4().hex[:8]}.db"
        self.service = StockReservationService(db_path=self.test_db)
        self.client_history = ClientHistoryService(db_path=self.test_db)
        self.now_iso = datetime.now(timezone.utc).isoformat()

        # Seed quote for testing
        self.pn = "060-1234-00"
        self.client_email = "buyer@turbowingaviation.com"
        self.quote_num = "QTE-2026-9812"
        self.rfq_id = "RFQ-2026-9812"
        self.unit_price = 2450.0

        self.client_history.record_client_quote(
            client_email=self.client_email,
            client_name="Turbowing Buyer",
            company_name="Turbowing Aviation",
            quote_number=self.quote_num,
            rfq_id=self.rfq_id,
            part_number=self.pn,
            unit_price=self.unit_price,
            quantity=1,
            condition="NE",
            certification="FAA 8130-3 Dual Release",
            lead_time="Stock",
            sent_at=self.now_iso,
        )

    def tearDown(self):
        import os
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except Exception:
                pass

    def test_check_part_quoted_today_same_client(self):
        res = self.service.check_part_quoted_today(self.pn, self.client_email)
        self.assertIsNotNone(res)
        self.assertTrue(res["quoted_today"])
        self.assertTrue(res["is_same_client"])
        self.assertEqual(res["quote_number"], self.quote_num)
        self.assertEqual(res["unit_price"], self.unit_price)

    def test_check_part_quoted_today_different_client_generates_new_rfq(self):
        diff_email = "newbuyer@differentairline.com"
        res = self.service.check_part_quoted_today(self.pn, diff_email)
        self.assertIsNotNone(res)
        self.assertTrue(res["quoted_today"])
        self.assertFalse(res["is_same_client"])
        # Must generate new RFQ number as required
        self.assertTrue(res["rfq_id"].startswith("RFQ-"))
        self.assertNotEqual(res["rfq_id"], self.rfq_id)
        self.assertEqual(res["unit_price"], self.unit_price)

    def test_create_and_get_stock_hold(self):
        hold = self.service.create_stock_hold(
            client_email=self.client_email,
            company_name="Turbowing Aviation",
            part_number=self.pn,
            quote_number=self.quote_num,
            unit_price=self.unit_price,
            quantity=1,
            duration_minutes=120,
        )
        self.assertEqual(hold["status"], "ACTIVE")
        self.assertGreater(hold["remaining_seconds"], 7100)
        self.assertLessEqual(hold["remaining_seconds"], 7200)

        # Retrieve active hold
        active = self.service.get_active_hold_for_client(self.client_email)
        self.assertIsNotNone(active)
        self.assertEqual(active["reservation_id"], hold["reservation_id"])
        self.assertEqual(active["part_number"], self.pn)

    def test_release_and_convert_hold(self):
        hold = self.service.create_stock_hold(
            client_email=self.client_email,
            company_name="Turbowing Aviation",
            part_number=self.pn,
            quote_number=self.quote_num,
            unit_price=self.unit_price,
            quantity=1,
        )
        # Convert to order
        converted = self.service.convert_hold_to_order(self.quote_num, "PO-9999", self.client_email)
        self.assertTrue(converted)

        # Once converted, active hold should be None
        active = self.service.get_active_hold_for_client(self.client_email)
        self.assertIsNone(active)


if __name__ == "__main__":
    unittest.main()
