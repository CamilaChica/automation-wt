import asyncio
import os
import unittest
from unittest import mock

from services import partsbase_service as pb


class FakeLocator:
    def __init__(self, page, selector, index=None):
        self.page = page
        self.selector = selector
        self.index = index

    @property
    def first(self):
        return self

    def nth(self, _index):
        return FakeLocator(self.page, self.selector, _index)

    def filter(self, **_kwargs):
        return self

    def locator(self, selector):
        return FakeLocator(self.page, f"{self.selector} {selector}", self.index)

    async def count(self):
        if self.selector == "div.floating-bar-selected-item-div":
            return len(self.page.found)
        if self.selector.endswith("input.floating-bar-selected-item-box-quantity-input"):
            return int(self.index is not None and self.index < len(self.page.found))
        if self.selector.startswith("input#selected-items-checkbox-"):
            return 1 if self.selector.rsplit("-", 1)[-1] in self.page.found else 0
        if self.selector.startswith("label.switch"):
            return 1
        return 1

    async def inner_text(self):
        if self.selector == "div.floating-bar-selected-item-div":
            return f"{sorted(self.page.found)[self.index]}\nQTY"
        if "xpath=.." in self.selector:
            return "Show all results in one tab"
        return "Show all results in one tab"

    async def is_checked(self):
        return False

    async def check(self):
        self.page.actions.append(("check", self.selector))

    async def fill(self, value):
        part = sorted(self.page.found)[self.index]
        self.page.quantity_values[part] = value
        self.page.actions.append(("fill", self.selector, part, value))

    async def input_value(self):
        part = sorted(self.page.found)[self.index]
        return self.page.quantity_values[part]

    async def click(self, **_kwargs):
        self.page.actions.append(("click", self.selector))


class FakePage:
    def __init__(self, found=("ABC123", "XYZ9")):
        self.found = set(found)
        self.actions = []
        self.quantity_values = {part: "1" for part in self.found}

    async def goto(self, url, **_kwargs):
        self.actions.append(("goto", url))

    async def fill(self, selector, value):
        self.actions.append(("fill", selector, value))

    async def click(self, selector, **_kwargs):
        self.actions.append(("click", selector))

    async def wait_for_selector(self, *_args, **_kwargs):
        return None

    async def wait_for_url(self, *_args, **_kwargs):
        return None

    async def wait_for_timeout(self, *_args):
        return None

    def locator(self, selector):
        return FakeLocator(self, selector)

    def get_by_text(self, text, exact=True):
        return FakeLocator(self, f"text={text}")


CREDS = {"PARTSBASE_USERNAME": "user", "PARTSBASE_PASSWORD": "pw"}


class NormalizeTests(unittest.TestCase):
    def test_splits_dedupes_and_uppercases(self):
        self.assertEqual(pb.normalize_part_numbers(" abc123, ABC123;xyz9\n"), ["ABC123", "XYZ9"])

    def test_rejects_empty_and_more_than_twenty(self):
        with self.assertRaises(ValueError):
            pb.normalize_part_numbers(" , ")
        with self.assertRaises(ValueError):
            pb.normalize_part_numbers([f"P{i}" for i in range(21)])


class FlowTests(unittest.TestCase):
    def test_flow_searches_and_sends_only_needed_parts(self):
        page = FakePage()
        asyncio.run(pb.run_partsbase_flow(
            page, ["ABC123", "XYZ9"], "user", "pw", {"ABC123": 4, "XYZ9": 2}
        ))
        self.assertIn(("fill", "textarea#search", "ABC123, XYZ9"), page.actions)
        self.assertIn(("check", "input#selected-items-checkbox-ABC123"), page.actions)
        self.assertIn(("check", "input#selected-items-checkbox-XYZ9"), page.actions)
        self.assertEqual(page.quantity_values, {"ABC123": "4", "XYZ9": "2"})
        self.assertIn(("click", "text=Send RFQ"), page.actions)
        self.assertLess(page.actions.index(("click", "text=Deselect All")),
                        page.actions.index(("check", "input#selected-items-checkbox-ABC123")))

    def test_flow_fails_when_no_part_found(self):
        with self.assertRaises(pb.PartsBaseError):
            asyncio.run(pb.run_partsbase_flow(
                FakePage(found=()), ["NOPE1"], "user", "pw", {"NOPE1": 1}
            ))

    def test_quantity_is_required_for_every_part(self):
        with self.assertRaisesRegex(ValueError, "exactly one requested quantity"):
            pb.normalize_quantities(["ABC123", "XYZ9"], {"ABC123": 2})
        with self.assertRaisesRegex(ValueError, "positive integer"):
            pb.normalize_quantities(["ABC123"], {"ABC123": 0})
        self.assertEqual(
            pb.normalize_quantities(["ABC123"], {"abc123": 5}),
            {"ABC123": 5},
        )


class JobTests(unittest.TestCase):
    def test_missing_credentials(self):
        with mock.patch.dict(os.environ, {"PARTSBASE_USERNAME": "", "PARTSBASE_PASSWORD": ""}):
            self.assertFalse(pb.credentials_configured())
            with self.assertRaises(pb.PartsBaseError):
                asyncio.run(pb.request_partsbase_quote(
                    ["ABC123"], quantities={"ABC123": 1}, page_runner=mock.AsyncMock()
                ))

    def test_job_sent_and_failed(self):
        async def ok_runner(flow):
            await flow(FakePage())

        async def broken_runner(_flow):
            raise TimeoutError("PartsBase timed out")

        with mock.patch.dict(os.environ, CREDS):
            job = pb.start_job("RFQ-1", ["ABC123"], {"ABC123": 3}, "sales@wingedtycoons.com")
            self.assertEqual(asyncio.run(pb.run_job(job["job_id"], page_runner=ok_runner))["status"], "sent")
            job = pb.start_job("RFQ-2", ["ABC123"], {"ABC123": 3}, "sales@wingedtycoons.com")
            result = asyncio.run(pb.run_job(job["job_id"], page_runner=broken_runner))
        self.assertEqual(result["status"], "failed")
        self.assertIn("timed out", result["error"])
        self.assertIs(pb.get_job(job["job_id"]), result)


if __name__ == "__main__":
    unittest.main()
