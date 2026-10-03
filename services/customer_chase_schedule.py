"""Shared configuration for delayed customer quote chases."""

from __future__ import annotations

import os


def chase_days() -> list[int]:
    raw = os.getenv("CUSTOMER_CHASE_SCHEDULE_DAYS", "1,3,7")
    days = []
    for value in raw.split(","):
        try:
            day = int(value.strip())
        except ValueError:
            continue
        if day > 0 and day not in days:
            days.append(day)
    return days or [1, 3, 7]


def chase_task_keys(quote_id: str) -> list[str]:
    return [
        f"customer-followup:{quote_id}" if index == 1 else f"customer-followup:{quote_id}:{index}"
        for index, _day in enumerate(chase_days(), start=1)
    ]


def final_chase_day() -> int:
    """Return the last configured delay for the single customer follow-up."""
    return max(chase_days())