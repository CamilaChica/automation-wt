import tempfile
import unittest
from pathlib import Path

from services.purchasing_email_parser import ingest_supplier_quote_email
from services.relational_db import db_connection, ensure_schema, seed_relational_mock_data


class PurchasingEmailParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "parser_test.db"
        ensure_schema(self.db_path)
        seed_relational_mock_data(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_ingest_creates_new_supplier_and_inventory(self) -> None:
        raw_email = (
            "From: quotes@skybridgeparts.com\n"
            "Subject: Quote for WT\n\n"
            "Part Number: 777-ABC-11\n"
            "Condition: NE\n"
            "Price: 1999.50\n"
            "Quantity: 6\n"
            "Lead Time: 7\n"
            "Description: Flight control module\n"
            "Location: Miami Hub\n"
        )
        result = ingest_supplier_quote_email(raw_email, "email-001", self.db_path)

        with db_connection(self.db_path) as connection:
            supplier = connection.execute(
                "SELECT id, email FROM suppliers WHERE id = ?",
                (result["supplier_id"],),
            ).fetchone()
            item = connection.execute(
                "SELECT clean_part_number, quantity_available, unit_cost_usd, source_email_id FROM inventory_items WHERE id = ?",
                (result["inventory_item_id"],),
            ).fetchone()

        self.assertIsNotNone(supplier)
        self.assertEqual(supplier["email"], "quotes@skybridgeparts.com")
        self.assertEqual(item["clean_part_number"], "777-ABC-11")
        self.assertEqual(item["quantity_available"], 6)
        self.assertAlmostEqual(item["unit_cost_usd"], 1999.50)
        self.assertEqual(item["source_email_id"], "email-001")

    def test_ingest_upserts_existing_supplier_part_condition(self) -> None:
        first_email = (
            "From: quotes@apexaero.com\n"
            "Part Number: 060-1234-00\n"
            "Condition: NE\n"
            "Price: 1100\n"
            "Quantity: 4\n"
            "Lead Time: 3\n"
        )
        second_email = (
            "From: quotes@apexaero.com\n"
            "Part Number: 060-1234-00\n"
            "Condition: NE\n"
            "Price: 950\n"
            "Quantity: 9\n"
            "Lead Time: 1\n"
        )

        first = ingest_supplier_quote_email(first_email, "email-100", self.db_path)
        second = ingest_supplier_quote_email(second_email, "email-101", self.db_path)

        self.assertEqual(first["inventory_item_id"], second["inventory_item_id"])

        with db_connection(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT quantity_available, unit_cost_usd, source_email_id
                FROM inventory_items
                WHERE id = ?
                """,
                (first["inventory_item_id"],),
            ).fetchone()

        self.assertEqual(row["quantity_available"], 9)
        self.assertAlmostEqual(row["unit_cost_usd"], 950.0)
        self.assertEqual(row["source_email_id"], "email-101")

    def test_ingest_is_idempotent_for_same_source_email_id(self) -> None:
        raw_email = (
            "From: quotes@apexaero.com\n"
            "Part Number: 060-1234-00\n"
            "Condition: NE\n"
            "Price: 980\n"
            "Quantity: 8\n"
            "Lead Time: 2\n"
        )
        first = ingest_supplier_quote_email(raw_email, "email-idempotent", self.db_path)
        second = ingest_supplier_quote_email(raw_email, "email-idempotent", self.db_path)

        self.assertEqual(first["inventory_item_id"], second["inventory_item_id"])

        with db_connection(self.db_path) as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM purchasing_email_ingestion WHERE source_email_id = ?",
                ("email-idempotent",),
            ).fetchone()["count"]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
