from typing import Dict, Any
from tools.base_tool import BaseTool, ToolMetadata
from services.db_service import db_service
from services.supplier_database import supplier_db

class SearchPartsCatalogTool(BaseTool):
    def __init__(self):
        metadata = ToolMetadata(
            name="search_parts_catalog",
            description="Looks up exact part numbers in persisted inventory and supplier-offer records.",
            input_schema={
                "type": "object",
                "properties": {
                    "part_number": {"type": "string", "description": "The aerospace part number to look up"}
                },
                "required": ["part_number"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "found": {"type": "boolean"},
                    "match_type": {"type": "string", "description": "exact or none"},
                    "parts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "part_number": {"type": "string"},
                                "description": {"type": "string"},
                                "manufacturer": {"type": "string"},
                                "category": {"type": "string"},
                                "aircraft_applicability": {"type": "string"},
                                "condition": {"type": "string"},
                                "alternate_part_numbers": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                },
                                "documentation_requirements": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                }
                            }
                        }
                    }
                }
            }
        )
        super().__init__(metadata)

    async def run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        part_number = args.get("part_number", "").strip().upper()
        if not part_number:
            return {"found": False, "match_type": "none", "parts": []}

        inventory_records = [
            record for record in db_service.inventory.values()
            if record.part_number.strip().upper() == part_number
        ]
        supplier_offers = supplier_db.find_supplier_offers(part_number, quantity_needed=1)
        if not inventory_records and not supplier_offers:
            return {"found": False, "match_type": "none", "parts": []}

        inventory_record = inventory_records[0] if inventory_records else None
        supplier_offer = supplier_offers[0] if supplier_offers else {}
        certificate_types = list(dict.fromkeys(
            certificate for certificate in (
                [getattr(record, "certificate_type", None) for record in inventory_records]
                + [offer.get("certificate_type") for offer in supplier_offers]
            )
            if certificate and certificate != "None"
        ))
        return {
            "found": True,
            "match_type": "exact",
            "parts": [{
                "part_number": part_number,
                "description": supplier_offer.get("description", ""),
                "manufacturer": "",
                "category": "",
                "aircraft_applicability": "",
                "condition": (
                    getattr(inventory_record, "condition_code", "")
                    if inventory_record
                    else supplier_offer.get("condition_code", "")
                ),
                "alternate_part_numbers": [],
                "documentation_requirements": certificate_types,
            }],
        }


# ---------------------------------------------------------------------------
# CheckInventoryTool
# ---------------------------------------------------------------------------
# Availability status codes returned in the response
AVAILABILITY_STATUS_IN_STOCK       = "IN_STOCK"        # full quantity available
AVAILABILITY_STATUS_PARTIAL        = "PARTIAL_OR_SHORTAGE"  # partial or zero stock
AVAILABILITY_STATUS_NOT_FOUND      = "NOT_FOUND"       # part not in inventory system


class CheckInventoryTool(BaseTool):
    """
    Tool: check_inventory
    ---------------------
    Queries persisted internal inventory records for a given part number and
    requested quantity.

    Uses the persisted quantity_available value. Reservation counts are not part
    of the current inventory record model.

    Returns a standardised availability response.  Never invents inventory —
    if the part is unknown the response will reflect zero availability.

    Availability status rules:
        IN_STOCK              – persisted quantity_available >= requested_quantity
        PARTIAL_OR_SHORTAGE   – persisted quantity_available < requested_quantity
        NOT_FOUND             – part number is not in the inventory database
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="check_inventory",
            description=(
                "Queries the internal warehouse inventory for a part number and a "
                "requested quantity. Returns persisted quantity available, shortage, "
                "condition, warehouse, and availability status. Does not infer reservations."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "part_number": {
                        "type": "string",
                        "description": "Canonical part number to look up (case-insensitive)"
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "Requested quantity to fulfil"
                    }
                },
                "required": ["part_number", "quantity"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "requested_quantity":   {"type": "integer"},
                    "available_quantity":   {"type": "integer",
                                            "description": "Quantity available in persisted inventory records"},
                    "shortage_quantity":    {"type": "integer",
                                            "description": "Max(0, requested_quantity - available_quantity)"},
                    "condition":            {"type": "string",
                                            "description": "Airworthiness condition code: NE, NS, OH, AR"},
                    "warehouse":            {"type": "string"},
                    "location":             {"type": "string"},
                    "lead_time":            {"type": "string"},
                    "availability_status":  {"type": "string",
                                            "enum": [
                                                AVAILABILITY_STATUS_IN_STOCK,
                                                AVAILABILITY_STATUS_PARTIAL,
                                                AVAILABILITY_STATUS_NOT_FOUND
                                            ]},
                    # Extended fields for downstream pipeline use
                    "quantity_on_hand":     {"type": "integer"},
                    "quantity_reserved":    {"type": "integer"},
                    "status":               {"type": "string"},
                    "unit_cost":            {"type": "number"},
                    "certificate_type":     {"type": "string"},
                    "has_full_trace":       {"type": "boolean"}
                },
                "required": [
                    "requested_quantity", "available_quantity", "shortage_quantity",
                    "condition", "warehouse", "location", "lead_time", "availability_status"
                ]
            }
        )
        super().__init__(metadata)

    async def run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        raw_pn: str = args.get("part_number", "")
        part_number: str = raw_pn.strip().upper()
        requested_qty: int = max(0, int(args.get("quantity", 1)))

        # Aggregate persisted lots for the exact part number.
        matching_records = [
            record for record in db_service.inventory.values()
            if record.part_number.strip().upper() == part_number
        ]

        if not matching_records:
            # Part is completely unknown — do NOT invent any inventory
            return {
                "requested_quantity":  requested_qty,
                "available_quantity":  0,
                "shortage_quantity":   requested_qty,
                "condition":           "UNKNOWN",
                "warehouse":           "N/A",
                "location":            "N/A",
                "lead_time":           "N/A",
                "availability_status": AVAILABILITY_STATUS_NOT_FOUND,
                # Extended fields
                "quantity_on_hand":    0,
                "quantity_reserved":   0,
                "status":              "NOT_FOUND",
                "unit_cost":           0.0,
                "certificate_type":    "None",
                "has_full_trace":      False,
            }

        # Aggregate across all matching records
        total_on_hand: int = sum(record.quantity_available for record in matching_records)
        total_reserved = 0
        available_to_promise: int = max(0, total_on_hand - total_reserved)

        # Use the first persisted lot for location and condition metadata.
        primary = matching_records[0]

        shortage_qty: int = max(0, requested_qty - available_to_promise)

        # Determine availability status
        if available_to_promise >= requested_qty:
            availability_status = AVAILABILITY_STATUS_IN_STOCK
        else:
            availability_status = AVAILABILITY_STATUS_PARTIAL

        # Determine combined traceability (all records must have full trace)
        has_full_trace: bool = all(record.has_full_trace for record in matching_records)

        return {
            "requested_quantity":  requested_qty,
            "available_quantity":  available_to_promise,
            "shortage_quantity":   shortage_qty,
            "condition":           primary.condition_code,
            "warehouse":           primary.warehouse_location,
            "location":            primary.warehouse_location,
            "lead_time":            "N/A",
            "availability_status": availability_status,
            # Extended fields for downstream pipeline use
            "quantity_on_hand":    total_on_hand,
            "quantity_reserved":   total_reserved,
            "status":              "ACTIVE",
            "unit_cost":           primary.unit_cost,
            "certificate_type":    primary.certificate_type,
            "has_full_trace":      has_full_trace,
        }
