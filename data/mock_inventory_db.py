"""
Mock Inventory Database
-----------------------
Represents a physical warehouse stock table.

Fields per record:
  part_number       – Canonical part number (primary key)
  quantity_on_hand  – Total physical units in the warehouse
  quantity_reserved – Units already committed / soft-allocated to open orders
  condition         – Airworthiness condition code (NE, NS, OH, AR)
  warehouse         – Warehouse identifier
  location          – Bin / aisle / shelf location string
  lead_time         – Estimated ready-to-ship lead time (string label)
  status            – Record status: ACTIVE | QUARANTINED | INACTIVE

Derived (computed at query time):
  available_to_promise = quantity_on_hand - quantity_reserved

Additional fields retained for downstream pipeline compatibility:
  unit_cost         – Internal acquisition cost per unit (USD)
  certificate_type  – Airworthiness certificate type held on file
  has_full_trace    – Whether back-to-birth traceability documentation is complete
"""

from typing import Dict, Any

MOCK_INVENTORY_DB: Dict[str, Dict[str, Any]] = {
    "060-1234-00": {
        "part_number":        "060-1234-00",
        "quantity_on_hand":   5,
        "quantity_reserved":  3,   # ATP = 5 - 3 = 2
        "condition":          "NE",
        "warehouse":          "WHSE-A",
        "location":           "Aisle 3, Bin B4",
        "lead_time":          "2 days",
        "status":             "ACTIVE",
        # Pipeline compatibility fields
        "unit_cost":          1000.00,
        "certificate_type":   "FAA 8130-3",
        "has_full_trace":     True,
    },
    "456-789-OH": {
        "part_number":        "456-789-OH",
        "quantity_on_hand":   3,
        "quantity_reserved":  1,   # ATP = 3 - 1 = 2
        "condition":          "OH",
        "warehouse":          "WHSE-B",
        "location":           "Aisle 12, Bin C1",
        "lead_time":          "5 days",
        "status":             "ACTIVE",
        # Pipeline compatibility fields
        "unit_cost":          450.00,
        "certificate_type":   "EASA Form 1",
        "has_full_trace":     True,
    },
    "456-789-OH-TRACE": {
        # Second batch of 456-789-OH with incomplete traceability (drives compliance warning test)
        "part_number":        "456-789-OH",
        "quantity_on_hand":   2,
        "quantity_reserved":  1,   # ATP = 2 - 1 = 1
        "condition":          "OH",
        "warehouse":          "WHSE-B",
        "location":           "Aisle 12, Bin C2",
        "lead_time":          "5 days",
        "status":             "ACTIVE",
        # Pipeline compatibility fields
        "unit_cost":          450.00,
        "certificate_type":   "FAA 8130-3",
        "has_full_trace":     False,   # Missing back-to-birth trace — triggers compliance warning
    },
}
