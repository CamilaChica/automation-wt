"""Owner analytics, per-rep sales and the shared sales race, computed from live PostgreSQL data."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.employee_profile_service import work_hours_report

AI_ACTOR = "AI Automation"


def current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


async def _rows(session: AsyncSession, sql: str, params: dict | None = None) -> list[dict]:
    return [dict(r) for r in (await session.execute(text(sql), params or {})).mappings().all()]


async def _rep_revenue(session: AsyncSession) -> dict[str, dict]:
    """Attribute purchase orders to the human actor recorded in audit_events; otherwise to AI automation."""
    rows = await _rows(session, """
        SELECT po.id::text AS po_id, COALESCE(po.total_amount, 0)::float AS amount,
               (SELECT lower(a.actor) FROM audit_events a
                 WHERE a.actor LIKE '%@%'
                   AND a.entity_id IN (po.id::text, po.po_number, po.quote_id::text, po.rfq_id::text)
                 ORDER BY a.created_at DESC LIMIT 1) AS actor
        FROM purchase_orders po
    """)
    totals: dict[str, dict] = {}
    for row in rows:
        key = row["actor"] or AI_ACTOR
        entry = totals.setdefault(key, {"revenue": 0.0, "orders": 0})
        entry["revenue"] += row["amount"]
        entry["orders"] += 1
    return totals


async def owner_overview(session: AsyncSession) -> dict:
    month = current_month()
    rfq_status = await _rows(session, "SELECT status, count(*)::int AS count FROM rfqs GROUP BY status ORDER BY 2 DESC")
    daily = await _rows(session, """
        SELECT to_char(date_trunc('day', created_at), 'YYYY-MM-DD') AS day, count(*)::int AS count
        FROM rfqs WHERE created_at >= now() - interval '30 days' GROUP BY 1 ORDER BY 1
    """)
    quotes = (await _rows(session, """
        SELECT count(*)::int AS count, COALESCE(sum(total_price), 0)::float AS value FROM customer_quotes
    """))[0]
    orders = (await _rows(session, """
        SELECT count(*)::int AS count, COALESCE(sum(total_amount), 0)::float AS value FROM purchase_orders
    """))[0]
    customers = await _rows(session, """
        SELECT COALESCE(NULLIF(customer_name, ''), customer_email, 'Unknown') AS customer, count(*)::int AS rfqs
        FROM rfqs GROUP BY 1 ORDER BY 2 DESC LIMIT 8
    """)
    parts = await _rows(session, """
        SELECT part_number, count(*)::int AS rfqs FROM rfqs
        WHERE part_number IS NOT NULL AND part_number <> ''
          AND upper(part_number) NOT IN ('DESCRIPTION', 'PART NUMBER', 'PN', 'N/A', 'UNKNOWN') GROUP BY 1 ORDER BY 2 DESC LIMIT 8
    """)
    total_rfqs = sum(r["count"] for r in rfq_status)
    hours = await work_hours_report(session, month)
    return {
        "month": month,
        "kpis": {
            "total_rfqs": total_rfqs,
            "rfqs_last_30_days": sum(d["count"] for d in daily),
            "quotes_sent": quotes["count"],
            "quoted_value": quotes["value"],
            "purchase_orders": orders["count"],
            "revenue": orders["value"],
            "quote_rate": round(quotes["count"] / total_rfqs * 100, 1) if total_rfqs else 0.0,
            "win_rate": round(orders["count"] / quotes["count"] * 100, 1) if quotes["count"] else 0.0,
        },
        "rfq_status": rfq_status,
        "daily_rfqs": daily,
        "top_customers": customers,
        "top_parts": parts,
        "team": await sales_leaderboard(session, hours),
    }


async def sales_leaderboard(session: AsyncSession, hours: dict | None = None) -> list[dict]:
    hours = hours or await work_hours_report(session, current_month())
    revenue = await _rep_revenue(session)
    board = []
    for emp in hours["employees"]:
        rep = revenue.pop(emp["email"].lower(), {"revenue": 0.0, "orders": 0})
        board.append({
            "name": emp["display_name"] or emp["email"],
            "email": emp["email"],
            "revenue": round(rep["revenue"], 2),
            "orders": rep["orders"],
            "hours": round(emp["total_seconds"] / 3600, 1),
            "is_online": emp["is_online"],
        })
    for actor, rep in revenue.items():
        board.append({"name": actor, "email": "" if actor == AI_ACTOR else actor, "revenue": round(rep["revenue"], 2),
                      "orders": rep["orders"], "hours": 0.0, "is_online": actor == AI_ACTOR})
    board.sort(key=lambda r: (-r["revenue"], -r["hours"], r["name"]))
    return board


async def my_sales(session: AsyncSession, user: dict) -> dict:
    month = current_month()
    hours = await work_hours_report(session, month, user["id"])
    me = hours["employees"][0] if hours["employees"] else {"total_seconds": 0, "daily_seconds": {}}
    rep = (await _rep_revenue(session)).get(user["email"].lower(), {"revenue": 0.0, "orders": 0})
    handled = await _rows(session, """
        SELECT DISTINCT r.id::text AS rfq_id, r.part_number, r.customer_email, r.status, r.created_at
        FROM audit_events a JOIN rfqs r ON a.entity_id = r.id::text
        WHERE lower(a.actor) = lower(:email) ORDER BY r.created_at DESC LIMIT 20
    """, {"email": user["email"]})
    for row in handled:
        row["created_at"] = row["created_at"].isoformat() if row["created_at"] else None
    return {
        "month": month,
        "revenue": round(rep["revenue"], 2),
        "orders": rep["orders"],
        "hours": round(me["total_seconds"] / 3600, 1),
        "daily_seconds": me["daily_seconds"],
        "handled_rfqs": handled,
    }
