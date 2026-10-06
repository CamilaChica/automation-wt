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

    def test_zero_quoted_cost_in_database_raises_value_error(self):
        from services.supplier_database import supplier_db
        with self.assertRaises(ValueError) as ctx:
            supplier_db.save_supplier_offer(
                supplier_name="Acme Aero",
                supplier_email="sales@acme.com",
                part_number="ABC-1234",
                quantity_available=5,
                unit_cost=0.0,
            )
        self.assertIn("must never be zero", str(ctx.exception).lower())

    def test_zero_cost_in_inventory_parser_returns_error(self):
        from services.supplier_inventory_parser import normalize_inventory_row
        row = {
            "part_number": "BACB30NM3-4",
            "quantity_available": "10",
            "unit_price": "$0.00",
        }
        _, error = normalize_inventory_row(row)
        self.assertIsNotNone(error)
        self.assertIn("must never be zero", error.lower())

    def test_zero_cost_in_email_extractor_raises_value_error(self):
        from services.supplier_email_extractor import supplier_email_extractor
        email_text = """
        From: sales@aerosupplies.com
        Subject: Quote for BACB30NM3-4
        Part: BACB30NM3-4
        Quantity: 5 EA
        Price: $0.00 each
        Condition: NE
        """
        with self.assertRaises(ValueError) as ctx:
            supplier_email_extractor.extract(email_text)
        self.assertIn("must never be zero", str(ctx.exception).lower())

    def test_no_quote_email_is_persisted_to_database_for_future_outreach(self):
        from services.supplier_ingestion_service import SupplierEmailIngestionService
        from services.supplier_database import supplier_db

        email_text = """From: quotes@aerodirect.com
Subject: RE: RFQ for BACB30NM3-4
We have no quote on part BACB30NM3-4. None in stock.
Regards,
AeroDirect Support Team"""

        result = SupplierEmailIngestionService().ingest_email(email_text)
        self.assertTrue(result["success"])
        self.assertTrue(result["no_quote"])
        self.assertEqual(result["status"], "Supplier_No_Quote")
        self.assertEqual(result["part_number"], "BACB30NM3-4")

        # Verify supplier is in database as a candidate for this part
        no_quote_sups = supplier_db.find_no_quote_suppliers("BACB30NM3-4")
        self.assertTrue(any("aerodirect" in (s.get("supplier_email") or "").lower() for s in no_quote_sups))

        candidates = supplier_db.find_candidate_suppliers_for_rfq("BACB30NM3-4")
        matched = [c for c in candidates if "aerodirect" in (c.get("supplier_email") or "").lower()]
        self.assertTrue(len(matched) > 0)
        self.assertEqual(matched[0]["was_no_quote"], 1)

    def test_future_rfq_prioritizes_candidate_no_quote_suppliers(self):
        from services.communication_service import communication_service
        from services.supplier_database import supplier_db

        # Seed a supplier that responded No Quote for XYZ-9900
        supplier_db.save_supplier_offer(
            supplier_name="Global Aviation Parts",
            supplier_email="rfq@globalaviationparts.com",
            part_number="XYZ-9900",
            quantity_available=0,
            unit_cost=None,
            approval_status="No_Quote",
        )

        candidates = supplier_db.find_candidate_suppliers_for_rfq("XYZ-9900")
        candidate_emails = [c.get("supplier_email") for c in candidates]
        self.assertIn("rfq@globalaviationparts.com", candidate_emails)


if __name__ == "__main__":
    unittest.main()
