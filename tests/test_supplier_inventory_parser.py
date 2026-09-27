import unittest
import io

from openpyxl import Workbook
from services.supplier_inventory_parser import normalize_inventory_row, parse_supplier_inventory_attachment


class TestSupplierInventoryParser(unittest.TestCase):
    def test_csv_headers_map_and_rows_are_preserved(self):
        content = (
            "Part Number,Description,Qty Available,Condition,Unit Price,Lead Time,Certificate,Location\n"
            "060-1234-00,Actuator,8,OH,$125.50,4 days,FAA 8130-3,Dallas\n"
        ).encode()

        tables = parse_supplier_inventory_attachment("stock.csv", "text/csv", content)

        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]["header_map"]["quantity_available"], "Qty Available")
        normalized, error = normalize_inventory_row(tables[0]["rows"][0])
        self.assertIsNone(error)
        self.assertEqual(normalized["part_number"], "060-1234-00")
        self.assertEqual(normalized["quantity_available"], 8)
        self.assertEqual(normalized["unit_price"], 125.5)
        self.assertEqual(normalized["condition_code"], "OH")

    def test_unstructured_csv_is_left_for_llm_fallback(self):
        content = b"Hello supplier, please quote part 060-1234-00\n"

        self.assertEqual(parse_supplier_inventory_attachment("note.csv", "text/csv", content), [])

    def test_xlsx_sheet_is_parsed_as_rows(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["PN", "Qty", "Condition"])
        sheet.append(["ABC-123", 4, "NS"])
        content = io.BytesIO()
        workbook.save(content)

        tables = parse_supplier_inventory_attachment("stock.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", content.getvalue())

        self.assertEqual(tables[0]["sheet_name"], "Sheet")
        self.assertEqual(tables[0]["rows"][0]["part_number"], "ABC-123")

    def test_rows_missing_part_or_quantity_are_rejected(self):
        normalized, error = normalize_inventory_row({"part_number": "", "quantity_available": "unknown"})

        self.assertIsNone(normalized["part_number"])
        self.assertEqual(error, "part_number is missing")


if __name__ == "__main__":
    unittest.main()