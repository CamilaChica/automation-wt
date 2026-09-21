import concurrent.futures
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from services.communication_service import CommunicationService
from services.db_service import db_service


class TestTimezoneAndInventoryReservation(unittest.TestCase):
    def test_followup_due_time_is_inside_customer_business_window(self):
        service = CommunicationService()
        result = service.schedule_customer_followup(
            recipient="buyer@example.com",
            customer_name="Buyer",
            quote_id="QTE-TZ-1",
            customer_timezone="America/Los_Angeles",
        )

        due = datetime.fromisoformat(result["due_at"]).astimezone(ZoneInfo("America/Los_Angeles"))
        self.assertLessEqual(0, due.weekday())
        self.assertLessEqual(due.weekday(), 4)
        self.assertGreaterEqual(due.hour, 8)
        self.assertLess(due.hour, 18)

    def test_two_reservations_cannot_overcommit_one_unit(self):
        part_number = "RESERVATION-TEST"
        original = dict(db_service.inventory)
        try:
            db_service.inventory = {}
            from models.db_models import InventoryItem
            db_service.inventory["INV-RESERVE"] = InventoryItem(
                id="INV-RESERVE",
                part_number=part_number,
                serial_number="SER-1",
                quantity_available=1,
                condition_code="NE",
                warehouse_location="TEST",
                unit_cost=1.0,
                certificate_type="CoC",
                has_full_trace=True,
            )
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: db_service.reserve_inventory(part_number, 1), range(2)))

            self.assertEqual(sorted(results), [False, True])
            self.assertEqual(db_service.inventory["INV-RESERVE"].quantity_available, 0)
        finally:
            db_service.inventory = original
            db_service._persist_state()


if __name__ == "__main__":
    unittest.main()
