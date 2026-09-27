"""PostgreSQL persistence for employee profiles, presence, and time-clock events."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
import json
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.async_database import create_engine_from_environment, session_scope


@asynccontextmanager
async def employee_session() -> AsyncIterator[AsyncSession]:
    engine = create_engine_from_environment()
    try:
        async with session_scope(engine) as session:
            yield session
    finally:
        await engine.dispose()


def _default_title(role: str) -> str:
    return role.removeprefix("ROLE_").replace("_", " ").title()


async def get_profile(session: AsyncSession, user: dict) -> dict:
    await session.execute(
        text("""
            INSERT INTO employee_profiles (user_id, email, display_name, job_title)
            VALUES (:user_id, :email, :display_name, :job_title)
            ON CONFLICT (user_id) DO NOTHING
        """),
        {
            "user_id": user["id"],
            "email": user["email"],
            "display_name": user.get("full_name") or user["email"].split("@", 1)[0],
            "job_title": _default_title(user.get("role", "Employee")),
        },
    )
    row = (await session.execute(
        text("""
            SELECT user_id, email, display_name, job_title, is_online, updated_at,
                COALESCE((SELECT event_type = 'clock_in' FROM employee_time_events
                 WHERE user_id = employee_profiles.user_id AND event_type IN ('clock_in', 'clock_out')
                 ORDER BY occurred_at DESC, id DESC LIMIT 1), FALSE) AS is_clocked_in
            FROM employee_profiles WHERE user_id = :user_id
        """),
        {"user_id": user["id"]},
    )).mappings().one()
    return dict(row)


async def update_profile(session: AsyncSession, user: dict, display_name: str, job_title: str) -> dict:
    previous = await get_profile(session, user)
    await session.execute(
        text("""
            UPDATE employee_profiles
            SET display_name = :display_name, job_title = :job_title, updated_at = now()
            WHERE user_id = :user_id
        """),
        {"user_id": user["id"], "display_name": display_name, "job_title": job_title},
    )
    await session.execute(
        text("""
            INSERT INTO employee_time_events (user_id, email, event_type, details)
            VALUES (:user_id, :email, 'profile_updated', CAST(:details AS jsonb))
        """),
        {
            "user_id": user["id"],
            "email": user["email"],
            "details": json.dumps({
                "display_name": {"from": previous["display_name"], "to": display_name},
                "job_title": {"from": previous["job_title"], "to": job_title},
            }),
        },
    )
    return await get_profile(session, user)


async def set_presence(session: AsyncSession, user: dict, is_online: bool) -> dict:
    profile = await get_profile(session, user)
    await session.execute(
        text("SELECT user_id FROM employee_profiles WHERE user_id = :user_id FOR UPDATE"),
        {"user_id": user["id"]},
    )
    profile = await get_profile(session, user)
    if bool(profile["is_online"]) != is_online:
        await session.execute(
            text("""
                UPDATE employee_profiles SET is_online = :is_online, updated_at = now()
                WHERE user_id = :user_id
            """),
            {"user_id": user["id"], "is_online": is_online},
        )
        await session.execute(
            text("""
                INSERT INTO employee_time_events (user_id, email, event_type)
                VALUES (:user_id, :email, :event_type)
            """),
            {
                "user_id": user["id"],
                "email": user["email"],
                "event_type": "presence_online" if is_online else "presence_offline",
            },
        )
    return await get_profile(session, user)


async def record_clock_event(session: AsyncSession, user: dict, action: str) -> dict:
    await get_profile(session, user)
    await session.execute(
        text("SELECT user_id FROM employee_profiles WHERE user_id = :user_id FOR UPDATE"),
        {"user_id": user["id"]},
    )
    previous = (await session.execute(
        text("""
            SELECT event_type FROM employee_time_events
            WHERE user_id = :user_id AND event_type IN ('clock_in', 'clock_out')
            ORDER BY occurred_at DESC, id DESC LIMIT 1
        """),
        {"user_id": user["id"]},
    )).scalar_one_or_none()
    if action == "clock_in" and previous == "clock_in":
        raise ValueError("You are already clocked in.")
    if action == "clock_out" and previous != "clock_in":
        raise ValueError("You are not currently clocked in.")
    await session.execute(
        text("""
            INSERT INTO employee_time_events (user_id, email, event_type)
            VALUES (:user_id, :email, :event_type)
        """),
        {"user_id": user["id"], "email": user["email"], "event_type": action},
    )
    return await get_profile(session, user)


def _month_bounds(month: str) -> tuple[datetime, datetime]:
    try:
        if len(month) != 7 or month[4] != "-" or not month[:4].isdigit() or not month[5:].isdigit():
            raise ValueError
        year, month_number = (int(part) for part in month.split("-", 1))
        start_date = date(year, month_number, 1)
    except (ValueError, TypeError):
        raise ValueError("Month must use YYYY-MM format.") from None
    if month_number == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month_number + 1, 1)
    return (
        datetime.combine(start_date, time.min, tzinfo=timezone.utc),
        datetime.combine(end_date, time.min, tzinfo=timezone.utc),
    )


def _add_interval(daily_seconds: dict[str, int], start: datetime, end: datetime) -> None:
    cursor = start
    while cursor < end:
        midnight = datetime.combine(cursor.date() + timedelta(days=1), time.min, tzinfo=timezone.utc)
        segment_end = min(end, midnight)
        day_key = cursor.date().isoformat()
        daily_seconds[day_key] = daily_seconds.get(day_key, 0) + int((segment_end - cursor).total_seconds())
        cursor = segment_end


async def work_hours_report(session: AsyncSession, month: str, user_id: str | None = None) -> dict:
    period_start, period_end = _month_bounds(month)
    filters = "AND p.user_id = :user_id" if user_id else ""
    profiles = (await session.execute(
        text(f"""
            SELECT p.user_id, p.email, p.display_name, p.job_title, p.is_online
            FROM employee_profiles p
            WHERE true {filters}
            ORDER BY p.display_name, p.email
        """),
        {"user_id": user_id} if user_id else {},
    )).mappings().all()
    employee_reports = []
    for profile in profiles:
        events = (await session.execute(
            text("""
                SELECT event_type, occurred_at FROM employee_time_events
                WHERE user_id = :user_id AND event_type IN ('clock_in', 'clock_out')
                  AND occurred_at < :period_end
                ORDER BY occurred_at, id
            """),
            {"user_id": profile["user_id"], "period_end": period_end},
        )).mappings().all()
        open_start: datetime | None = None
        daily_seconds: dict[str, int] = {}
        for event in events:
            occurred_at = event["occurred_at"]
            if event["event_type"] == "clock_in":
                open_start = occurred_at
            elif open_start is not None:
                clipped_start = max(open_start, period_start)
                clipped_end = min(occurred_at, period_end)
                if clipped_end > clipped_start:
                    _add_interval(daily_seconds, clipped_start, clipped_end)
                open_start = None
        if open_start is not None:
            now = datetime.now(timezone.utc)
            clipped_start = max(open_start, period_start)
            clipped_end = min(now, period_end)
            if clipped_end > clipped_start:
                _add_interval(daily_seconds, clipped_start, clipped_end)
        total_seconds = sum(daily_seconds.values())
        employee_reports.append({
            "email": profile["email"],
            "display_name": profile["display_name"],
            "job_title": profile["job_title"],
            "is_online": profile["is_online"],
            "total_seconds": total_seconds,
            "daily_seconds": daily_seconds,
        })
    return {"month": month, "employees": employee_reports}