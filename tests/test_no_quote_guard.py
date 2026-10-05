import unittest

from services.supplier_ingestion_service import is_no_quote_reply


class NoQuoteGuardTests(unittest.TestCase):
    def test_detects_no_quote_auto_reply(self):
        self.assertTrue(is_no_quote_reply("Subject: No Quote - RFQ 2117\n\nWe are unable to quote this item."))

    def test_detects_no_stock_without_price(self):
        self.assertTrue(is_no_quote_reply("Subject: RE: RFQ\n\nSorry, no stock available on this part."))

    def test_real_offer_is_not_blocked(self):
        self.assertFalse(is_no_quote_reply(
            "Subject: RE: RFQ 2117-1\n\nP/N 2117-1 OH qty 2 price $1,250.00 each, 8130-3, lead time stock."
        ))


if __name__ == "__main__":
    unittest.main()
