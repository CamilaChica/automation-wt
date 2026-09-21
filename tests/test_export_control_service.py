import unittest
from unittest.mock import patch

from services.export_control_service import ExportControlService


class TestExportControlService(unittest.TestCase):
    def test_denied_entity_is_blocked(self):
        service = ExportControlService()
        result = service.screen(
            customer_name="Blacklisted Co",
            raw_text="Request XYZ123",
            destination="United States",
        )

        self.assertTrue(result.blocked)
        self.assertTrue(any("Denied entity" in reason for reason in result.reasons))

    def test_denied_country_is_blocked(self):
        service = ExportControlService()
        result = service.screen(
            customer_name="Buyer",
            raw_text="Request XYZ123",
            destination="Iran",
        )

        self.assertTrue(result.blocked)
        self.assertTrue(any("Denied destination" in reason for reason in result.reasons))

    def test_restricted_part_requires_euc_without_denied_match(self):
        with patch.dict("os.environ", {"EXPORT_RESTRICTED_PART_PREFIXES": "MIL-"}, clear=False):
            result = ExportControlService().screen(
                customer_name="Approved Buyer",
                raw_text="Request MIL-123",
                destination="United States",
                part_number="MIL-123",
            )

        self.assertTrue(result.blocked)
        self.assertTrue(result.requires_euc)

    def test_restricted_part_in_rfq_text_requires_euc_even_without_explicit_part_number(self):
        with patch.dict("os.environ", {"EXPORT_RESTRICTED_PART_PREFIXES": "MIL-"}, clear=False):
            result = ExportControlService().screen(
                customer_name="Approved Buyer",
                raw_text="Need 2 EA of MIL-123 and ship to United States",
                destination="United States",
            )

        self.assertTrue(result.blocked)
        self.assertTrue(result.requires_euc)


if __name__ == "__main__":
    unittest.main()
