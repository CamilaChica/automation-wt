import unittest
from datetime import datetime, timezone

from services.employee_profile_service import _add_interval, _month_bounds


class EmployeeWorkHoursReportTests(unittest.TestCase):
    def test_month_bounds_cover_calendar_month(self):
        start, end = _month_bounds("2026-02")
        self.assertEqual(start, datetime(2026, 2, 1, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 3, 1, tzinfo=timezone.utc))

    def test_interval_is_split_at_midnight(self):
        daily_seconds = {}
        _add_interval(
            daily_seconds,
            datetime(2026, 9, 26, 23, 30, tzinfo=timezone.utc),
            datetime(2026, 9, 27, 1, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(daily_seconds, {"2026-09-26": 1800, "2026-09-27": 5400})

    def test_zero_length_interval_adds_no_hours(self):
        daily_seconds = {}
        instant = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
        _add_interval(daily_seconds, instant, instant)
        self.assertEqual(daily_seconds, {})

    def test_invalid_month_is_rejected(self):
        with self.assertRaises(ValueError):
            _month_bounds("2026-13")


if __name__ == "__main__":
    unittest.main()
