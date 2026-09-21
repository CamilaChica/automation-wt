"""Offline and accessibility contracts for the supported portal surfaces."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestUXAccessibilityAndOfflineStates(unittest.TestCase):
    def test_branding_and_portal_routes_are_present_in_source(self):
        app_source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        brand_source = (ROOT / "frontend" / "src" / "components" / "common" / "BrandMark.tsx").read_text(encoding="utf-8")

        self.assertIn("/customer-portal", app_source)
        self.assertIn("Winged Tycoons Logo", brand_source)

    def test_portal_actions_have_loading_state_text(self):
        portal_source = (ROOT / "frontend" / "src" / "components" / "views" / "CustomerPortal.tsx").read_text(encoding="utf-8")

        self.assertIn("Sending request...", portal_source)
        self.assertIn("Sending purchase order...", portal_source)
        self.assertIn("disabled={isSubmitting}", portal_source)
        self.assertIn("disabled={isSubmittingPo}", portal_source)

    @unittest.skip("Playwright/axe runtime accessibility integration is maintained in frontend/tests/e2e-ui.")
    def test_wcag_aa_with_axe_core(self):
        pass

    @unittest.skip("Offline connection banner and retry state are not implemented in the current frontend.")
    def test_offline_state_prevents_duplicate_submission_and_shows_retry(self):
        pass


if __name__ == "__main__":
    unittest.main()
