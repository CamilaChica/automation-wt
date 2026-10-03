"""Request supplier quotes on PartsBase by driving a headless browser.

Flow (recorded with the purchasing team):
login -> logo -> search part numbers -> "Show all results in one tab" (multi-part)
-> All conditions -> select all rows -> cart -> Add selected to RFQ
-> Deselect All -> select only the needed parts -> Send RFQ.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

LOGIN_URL = "https://app.partsbase.com/landing/login"
MAX_PARTS = 20
TIMEOUT_MS = 30_000

_jobs: dict[str, dict[str, Any]] = {}


class PartsBaseError(RuntimeError):
    pass


def normalize_part_numbers(raw: Any) -> list[str]:
    if isinstance(raw, str):
        items = re.split(r"[,\n;]+", raw)
    else:
        items = list(raw or [])
    seen: list[str] = []
    for item in items:
        part = str(item).strip().upper()
        if part and part not in seen:
            seen.append(part)
    if not seen:
        raise ValueError("At least one part number is required.")
    if len(seen) > MAX_PARTS:
        raise ValueError(f"PartsBase accepts up to {MAX_PARTS} part numbers per request.")
    return seen


def credentials_configured() -> bool:
    return bool(os.getenv("PARTSBASE_USERNAME") and os.getenv("PARTSBASE_PASSWORD"))


async def _click_text(page, text: str) -> None:
    await page.get_by_text(text, exact=True).first.click(timeout=TIMEOUT_MS)


async def run_partsbase_flow(page, part_numbers: list[str], username: str, password: str) -> None:
    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
    await page.fill("input#user", username)
    await page.fill("input#password", password)
    await page.click("button#loginBtn")
    await page.wait_for_selector("a#logoLoggedInDesk", timeout=TIMEOUT_MS)

    await page.click("a#logoLoggedInDesk")
    await page.wait_for_selector("textarea#search", timeout=TIMEOUT_MS)
    await page.fill("textarea#search", ", ".join(part_numbers))
    await page.click("button#btnSearchExecute")
    await page.wait_for_url("**/searchResults**", timeout=TIMEOUT_MS)
    await page.wait_for_selector("div#All.ccOption", timeout=TIMEOUT_MS)

    if len(part_numbers) > 1:
        switches = page.locator("label.switch")
        for index in range(await switches.count()):
            switch = switches.nth(index)
            if "Show all results in one tab" not in await switch.locator("xpath=..").inner_text():
                continue
            checkbox = switch.locator("input[type=checkbox]")
            if not (await checkbox.count() and await checkbox.is_checked()):
                await switch.click()
                await page.wait_for_timeout(1500)
            break

    await page.click("div#All.ccOption")
    await page.wait_for_timeout(1500)

    header = page.locator("tr.table-tr:not(.floatingHeaderNotDisplayed)").filter(has_text="PART NUMBER").first
    header_box = header.locator("input[type=checkbox]").first
    if not await header_box.is_checked():
        await header_box.check()

    await page.locator("div.new-floating-bar svg").first.click()
    await _click_text(page, "Add selected to RFQ")
    await page.wait_for_timeout(1500)

    await _click_text(page, "Deselect All")
    selected = 0
    for part in part_numbers:
        box = page.locator(f"input#selected-items-checkbox-{part}")
        if await box.count():
            await box.first.check()
            selected += 1
    if not selected:
        raise PartsBaseError("None of the requested parts were found on PartsBase.")

    await _click_text(page, "Send RFQ")
    await page.wait_for_timeout(2000)
    close = page.locator("button[aria-label=Close]")
    if await close.count():
        await close.first.click()


async def _default_page_runner(flow: Callable[[Any], Awaitable[None]]) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = await (await browser.new_context()).new_page()
            await flow(page)
        finally:
            await browser.close()


async def request_partsbase_quote(
    part_numbers: Any,
    page_runner: Optional[Callable[[Callable[[Any], Awaitable[None]]], Awaitable[None]]] = None,
) -> dict[str, Any]:
    parts = normalize_part_numbers(part_numbers)
    username = os.getenv("PARTSBASE_USERNAME", "")
    password = os.getenv("PARTSBASE_PASSWORD", "")
    if not (username and password):
        raise PartsBaseError("PartsBase login is not configured on the server.")
    runner = page_runner or _default_page_runner
    await runner(lambda page: run_partsbase_flow(page, parts, username, password))
    return {"part_numbers": parts, "status": "sent"}


def start_job(rfq_id: str, part_numbers: list[str], requested_by: str) -> dict[str, Any]:
    job = {
        "job_id": uuid.uuid4().hex[:12],
        "rfq_id": rfq_id,
        "part_numbers": part_numbers,
        "requested_by": requested_by,
        "status": "running",
        "error": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }
    _jobs[job["job_id"]] = job
    return job


async def run_job(job_id: str, page_runner=None) -> dict[str, Any]:
    job = _jobs[job_id]
    try:
        await request_partsbase_quote(job["part_numbers"], page_runner=page_runner)
        job["status"] = "sent"
    except Exception as exc:  # report any browser failure to the team
        logger.exception("PartsBase quote request failed for %s", job["rfq_id"])
        job["status"] = "failed"
        job["error"] = str(exc) or exc.__class__.__name__
    job["finished_at"] = datetime.now(timezone.utc).isoformat()
    return job


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    return _jobs.get(job_id)
