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


def normalize_quantities(part_numbers: list[str], quantities: Any) -> dict[str, int]:
    if not isinstance(quantities, dict):
        raise ValueError("A positive requested quantity is required for every part.")
    normalized: dict[str, int] = {}
    for raw_part, raw_quantity in quantities.items():
        part_number = str(raw_part or "").strip().upper()
        if not part_number or part_number in normalized:
            raise ValueError("Each PartsBase quantity must map to one unique part number.")
        if isinstance(raw_quantity, bool):
            raise ValueError(f"Requested quantity for {part_number} must be a positive integer.")
        try:
            quantity = int(raw_quantity)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Requested quantity for {part_number} must be a positive integer.") from exc
        if quantity < 1 or str(raw_quantity).strip() != str(quantity):
            raise ValueError(f"Requested quantity for {part_number} must be a positive integer.")
        normalized[part_number] = quantity
    if set(normalized) != set(part_numbers):
        raise ValueError("Provide exactly one requested quantity for every PartsBase part number.")
    return normalized


def credentials_configured() -> bool:
    return bool(os.getenv("PARTSBASE_USERNAME") and os.getenv("PARTSBASE_PASSWORD"))


async def _click_text(page, text: str) -> None:
    await page.get_by_text(text, exact=True).first.click(timeout=TIMEOUT_MS)


async def _set_requested_quantities(page, quantities: dict[str, int]) -> None:
    cards = page.locator("div.floating-bar-selected-item-div")
    matched: set[str] = set()
    for index in range(await cards.count()):
        card = cards.nth(index)
        label = (await card.inner_text()).splitlines()[0].strip().upper()
        if label not in quantities:
            continue
        if label in matched:
            raise PartsBaseError(f"PartsBase displayed more than one quantity field for {label}.")
        quantity_input = card.locator("input.floating-bar-selected-item-box-quantity-input")
        if await quantity_input.count() != 1:
            raise PartsBaseError(f"PartsBase quantity input was not available for {label}.")
        await quantity_input.fill(str(quantities[label]))
        if await quantity_input.input_value() != str(quantities[label]):
            raise PartsBaseError(f"PartsBase did not accept the requested quantity for {label}.")
        matched.add(label)
    missing = sorted(set(quantities) - matched)
    if missing:
        raise PartsBaseError(
            "PartsBase quantity inputs were not available for: " + ", ".join(missing)
        )


async def run_partsbase_flow(
    page,
    part_numbers: list[str],
    username: str,
    password: str,
    quantities: dict[str, int],
) -> None:
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

    await _set_requested_quantities(page, quantities)
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
    quantities: Any = None,
    page_runner: Optional[Callable[[Callable[[Any], Awaitable[None]]], Awaitable[None]]] = None,
) -> dict[str, Any]:
    parts = normalize_part_numbers(part_numbers)
    requested_quantities = normalize_quantities(parts, quantities)
    username = os.getenv("PARTSBASE_USERNAME", "")
    password = os.getenv("PARTSBASE_PASSWORD", "")
    if not (username and password):
        raise PartsBaseError("PartsBase login is not configured on the server.")
    runner = page_runner or _default_page_runner
    await runner(lambda page: run_partsbase_flow(page, parts, username, password, requested_quantities))
    return {"part_numbers": parts, "quantities": requested_quantities, "status": "sent"}


def start_job(
    rfq_id: str,
    part_numbers: list[str],
    quantities: dict[str, int],
    requested_by: str,
) -> dict[str, Any]:
    normalized_parts = normalize_part_numbers(part_numbers)
    normalized_quantities = normalize_quantities(normalized_parts, quantities)
    job = {
        "job_id": uuid.uuid4().hex[:12],
        "rfq_id": rfq_id,
        "part_numbers": normalized_parts,
        "quantities": normalized_quantities,
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
        await request_partsbase_quote(
            job["part_numbers"], quantities=job["quantities"], page_runner=page_runner
        )
        job["status"] = "sent"
    except Exception as exc:  # report any browser failure to the team
        logger.exception("PartsBase quote request failed for %s", job["rfq_id"])
        job["status"] = "failed"
        job["error"] = str(exc) or exc.__class__.__name__
    job["finished_at"] = datetime.now(timezone.utc).isoformat()
    return job


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    return _jobs.get(job_id)
