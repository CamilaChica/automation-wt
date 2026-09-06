from typing import Dict, Any, List, Optional
from tools.base_tool import BaseTool, ToolMetadata
from data.mock_inventory_db import MOCK_INVENTORY_DB

MOCK_PARTS_CATALOG = [
    {
        "part_number": "060-1234-00",
        "description": "Weather Radar Receiver-Transmitter",
        "manufacturer": "Honeywell",
        "category": "Avionics",
        "aircraft_applicability": "B737",
        "condition": "NE",
        "alternate_part_numbers": ["060-1234-01"],
        "documentation_requirements": ["FAA 8130-3", "CoC"]
    },
    {
        "part_number": "060-1234-01",
        "description": "Weather Radar Receiver-Transmitter (Upgrade)",
        "manufacturer": "Honeywell",
        "category": "Avionics",
        "aircraft_applicability": "B737",
        "condition": "NE",
        "alternate_part_numbers": ["060-1234-00"],
        "documentation_requirements": ["FAA 8130-3"]
    },
    {
        "part_number": "456-789-OH",
        "description": "Actuator Assembly",
        "manufacturer": "Liebherr",
        "category": "Flight Controls",
        "aircraft_applicability": "A320",
        "condition": "OH",
        "alternate_part_numbers": [],
        "documentation_requirements": ["EASA Form 1"]
    },
    {
        "part_number": "789-X-INVALID",
        "description": "Escalate test part",
        "manufacturer": "Unknown",
        "category": "Testing",
        "aircraft_applicability": "All",
        "condition": "AR",
        "alternate_part_numbers": [],
        "documentation_requirements": []
    },
    {
        "part_number": "MULTIPLE-123-A",
        "description": "Multi-Match Part A",
        "manufacturer": "Generic Aero",
        "category": "Hardware",
        "aircraft_applicability": "B777",
        "condition": "NE",
        "alternate_part_numbers": [],
        "documentation_requirements": ["CoC"]
    },
    {
        "part_number": "MULTIPLE-123-B",
        "description": "Multi-Match Part B",
        "manufacturer": "Generic Aero",
        "category": "Hardware",
        "aircraft_applicability": "B777",
        "condition": "NE",
        "alternate_part_numbers": [],
        "documentation_requirements": ["CoC"]
    }
]

class SearchPartsCatalogTool(BaseTool):
    def __init__(self):
        metadata = ToolMetadata(
            name="search_parts_catalog",
            description="Searches mock parts catalog by part number, supports exact, fuzzy and alternate parts search.",
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
                    "match_type": {"type": "string", "description": "exact, alternate, fuzzy, multiple, or none"},
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

        # 1. Exact matching
        exact_matches = [
            p for p in MOCK_PARTS_CATALOG
            if p["part_number"].upper() == part_number
        ]
        if exact_matches:
            if len(exact_matches) > 1:
                return {"found": True, "match_type": "multiple", "parts": exact_matches}
            return {"found": True, "match_type": "exact", "parts": exact_matches}

        clean_query = part_number.replace("-", "").replace(" ", "")

        # 2. Fuzzy matching (exact match on normalized string)
        fuzzy_matches = [
            p for p in MOCK_PARTS_CATALOG
            if p["part_number"].upper().replace("-", "").replace(" ", "") == clean_query
        ]
        if fuzzy_matches:
            if len(fuzzy_matches) > 1:
                return {"found": True, "match_type": "multiple", "parts": fuzzy_matches}
            return {"found": True, "match_type": "fuzzy", "parts": fuzzy_matches}

        # 3. Substring/prefix matching (fuzzy fallback)
        partial_matches = [
            p for p in MOCK_PARTS_CATALOG
            if clean_query in p["part_number"].upper().replace("-", "").replace(" ", "")
        ]
        if partial_matches:
            if len(partial_matches) > 1:
                return {"found": True, "match_type": "multiple", "parts": partial_matches}
            return {"found": True, "match_type": "fuzzy", "parts": partial_matches}

        # 4. Alternate matching
        alternate_matches = []
        for p in MOCK_PARTS_CATALOG:
            for alt in p.get("alternate_part_numbers", []):
                if alt.upper() == part_number or alt.upper().replace("-", "").replace(" ", "") == clean_query:
                    if p not in alternate_matches:
                        alternate_matches.append(p)

        if alternate_matches:
            if len(alternate_matches) > 1:
                return {"found": True, "match_type": "multiple", "parts": alternate_matches}
            return {"found": True, "match_type": "alternate", "parts": alternate_matches}

        return {"found": False, "match_type": "none", "parts": []}


class CatalogLookupTool(BaseTool):
    def __init__(self):
        metadata = ToolMetadata(
            name="catalog_lookup",
            description="Searches standard aviation parts catalogs by part number.",
            input_schema={
                "type": "object",
                "properties": {"part_number": {"type": "string"}},
                "required": ["part_number"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "found": {"type": "boolean"},
                    "resolved_part_number": {"type": "string"},
                    "description": {"type": "string"}
                }
            }
        )
        super().__init__(metadata)

    async def run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        pn = args.get("part_number", "").strip().upper()
        catalog = {
            "060-1234-00": "Weather Radar Receiver-Transmitter",
            "456-789-OH": "Actuator Assembly"
        }
        if pn in catalog:
            return {"found": True, "resolved_part_number": pn, "description": catalog[pn]}
        return {"found": False}


class InventorySearchTool(BaseTool):
    def __init__(self):
        metadata = ToolMetadata(
            name="inventory_search",
            description="Queries in-stock inventories, quantities, locations, and trace certifications.",
            input_schema={
                "type": "object",
                "properties": {"part_number": {"type": "string"}},
                "required": ["part_number"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "in_stock": {"type": "integer"},
                    "items": {"type": "array"}
                }
            }
        )
        super().__init__(metadata)

    async def run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        pn = args.get("part_number", "").strip().upper()
        # Mock stock return matching inventory_agent's mock DB
        if pn == "060-1234-00":
            return {
                "in_stock": 2,
                "items": [
                    {"serial_number": "SN-WR-001", "condition_code": "NE", "warehouse_location": "Aisle 3, Bin B4", "unit_cost": 1000.0, "certificate_type": "FAA 8130-3", "has_full_trace": True},
                    {"serial_number": "SN-WR-002", "condition_code": "NE", "warehouse_location": "Aisle 3, Bin B5", "unit_cost": 1000.0, "certificate_type": "FAA 8130-3", "has_full_trace": True}
                ]
            }
        elif pn == "456-789-OH":
            return {
                "in_stock": 2,
                "items": [
                    {"serial_number": "SN-ACT-981", "condition_code": "OH", "warehouse_location": "Aisle 12, Bin C1", "unit_cost": 450.0, "certificate_type": "EASA Form 1", "has_full_trace": True},
                    {"serial_number": "SN-ACT-982", "condition_code": "OH", "warehouse_location": "Aisle 12, Bin C2", "unit_cost": 450.0, "certificate_type": "FAA 8130-3", "has_full_trace": False}
                ]
            }
        return {"in_stock": 0, "items": []}


class SupplierNetworkSearchTool(BaseTool):
    def __init__(self):
        metadata = ToolMetadata(
            name="supplier_network_search",
            description="Searches partner supply networks for pricing and timelines.",
            input_schema={
                "type": "object",
                "properties": {"part_number": {"type": "string"}, "quantity_needed": {"type": "integer"}},
                "required": ["part_number", "quantity_needed"]
            },
            output_schema={
                "type": "object",
                "properties": {"supplier_quotes": {"type": "array"}}
            }
        )
        super().__init__(metadata)

    async def run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        pn = args.get("part_number", "").strip().upper()
        # Mock quotes matching supplier_discovery_agent's mock DB
        if pn == "060-1234-00":
            return {
                "supplier_quotes": [
                    {"supplier_name": "Apex Aero Components", "part_number": "060-1234-00", "unit_cost": 1100.00, "quantity_available": 10, "lead_time_days": 3, "certificate_type": "FAA 8130-3"},
                    {"supplier_name": "Vanguard Spares", "part_number": "060-1234-00", "unit_cost": 1050.00, "quantity_available": 3, "lead_time_days": 7, "certificate_type": "FAA 8130-3"}
                ]
            }
        elif pn == "456-789-OH":
            return {
                "supplier_quotes": [
                    {"supplier_name": "Horizon MRO Parts", "part_number": "456-789-OH", "unit_cost": 500.00, "quantity_available": 5, "lead_time_days": 2, "certificate_type": "FAA 8130-3"},
                    {"supplier_name": "Suspect Supplier Corp", "part_number": "456-789-OH", "unit_cost": 300.00, "quantity_available": 1, "lead_time_days": 1, "certificate_type": "None"}
                ]
            }
        return {"supplier_quotes": []}


class RegulatoryChecklistLookupTool(BaseTool):
    def __init__(self):
        metadata = ToolMetadata(
            name="regulatory_checklist_lookup",
            description="Checks regulatory requirements for part traceability and source verification.",
            input_schema={
                "type": "object",
                "properties": {"certificate_type": {"type": "string"}, "source": {"type": "string"}},
                "required": ["certificate_type"]
            },
            output_schema={
                "type": "object",
                "properties": {"is_compliant": {"type": "boolean"}, "reason": {"type": "string"}}
            }
        )
        super().__init__(metadata)

    async def run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        cert = args.get("certificate_type", "")
        source = args.get("source", "Inventory")
        
        valid_certs = ["FAA 8130-3", "EASA Form 1", "CoC"]
        if cert in valid_certs:
            return {"is_compliant": True, "reason": "Certificate is approved for civil aviation release."}
        if source == "Supplier":
            return {"is_compliant": False, "reason": "Sourced supplier parts must carry a valid FAA 8130-3 or EASA Form 1 release."}
        return {"is_compliant": False, "reason": "Missing primary airworthiness certificate."}


class MarginCalculatorTool(BaseTool):
    def __init__(self):
        metadata = ToolMetadata(
            name="margin_calculator",
            description="Calculates suggested unit prices based on margins or overrides.",
            input_schema={
                "type": "object",
                "properties": {"unit_cost": {"type": "number"}, "target_margin": {"type": "number"}},
                "required": ["unit_cost", "target_margin"]
            },
            output_schema={
                "type": "object",
                "properties": {"suggested_unit_price": {"type": "number"}}
            }
        )
        super().__init__(metadata)

    async def run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        cost = args.get("unit_cost", 0.0)
        margin = args.get("target_margin", 0.20)
        if margin >= 1.0 or margin <= -1.0:
            return {"suggested_unit_price": cost}
        price = cost / (1.0 - margin)
        return {"suggested_unit_price": round(price, 2)}


class ShippingEstimatorTool(BaseTool):
    def __init__(self):
        metadata = ToolMetadata(
            name="shipping_estimator",
            description="Estimates shipping and logistics costs based on urgency profiles.",
            input_schema={
                "type": "object",
                "properties": {"urgency": {"type": "string"}},
                "required": ["urgency"]
            },
            output_schema={
                "type": "object",
                "properties": {"shipping_cost": {"type": "number"}}
            }
        )
        super().__init__(metadata)

    async def run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        urgency = args.get("urgency", "Routine")
        if urgency == "AOG":
            return {"shipping_cost": 250.0}
        if urgency == "Expedite":
            return {"shipping_cost": 120.0}
        return {"shipping_cost": 50.0}


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
    Queries the internal mock inventory database for a given part number and
    requested quantity.

    Computes:
        available_to_promise = quantity_on_hand - quantity_reserved

    Returns a standardised availability response.  Never invents inventory —
    if the part is unknown the response will reflect zero availability.

    Availability status rules:
        IN_STOCK              – available_to_promise >= requested_quantity
        PARTIAL_OR_SHORTAGE   – 0 < available_to_promise < requested_quantity
                                OR available_to_promise == 0 but part exists
        NOT_FOUND             – part number is not in the inventory database
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="check_inventory",
            description=(
                "Queries the internal warehouse inventory for a part number and a "
                "requested quantity. Returns available_to_promise (ATP = quantity_on_hand "
                "- quantity_reserved), shortage quantity, condition, warehouse, location, "
                "lead_time, and availability_status. Never fabricates inventory data."
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
                                            "description": "ATP = quantity_on_hand - quantity_reserved"},
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

        # Lookup — search all records whose part_number matches (handles multiple
        # records for the same PN, e.g. different batches / trace status).
        # We aggregate quantity_on_hand and quantity_reserved across all matching
        # records but surface the first ACTIVE record's metadata.
        matching_records = [
            rec for rec in MOCK_INVENTORY_DB.values()
            if rec["part_number"].upper() == part_number
            and rec.get("status", "ACTIVE") != "INACTIVE"
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
        total_on_hand: int  = sum(r["quantity_on_hand"]  for r in matching_records)
        total_reserved: int = sum(r["quantity_reserved"] for r in matching_records)
        available_to_promise: int = max(0, total_on_hand - total_reserved)

        # Use the first ACTIVE record for location / condition metadata
        primary = matching_records[0]

        shortage_qty: int = max(0, requested_qty - available_to_promise)

        # Determine availability status
        if available_to_promise >= requested_qty:
            availability_status = AVAILABILITY_STATUS_IN_STOCK
        else:
            availability_status = AVAILABILITY_STATUS_PARTIAL

        # Determine combined traceability (all records must have full trace)
        has_full_trace: bool = all(r.get("has_full_trace", True) for r in matching_records)

        return {
            "requested_quantity":  requested_qty,
            "available_quantity":  available_to_promise,
            "shortage_quantity":   shortage_qty,
            "condition":           primary.get("condition", "UNKNOWN"),
            "warehouse":           primary.get("warehouse", "N/A"),
            "location":            primary.get("location", "N/A"),
            "lead_time":           primary.get("lead_time", "N/A"),
            "availability_status": availability_status,
            # Extended fields for downstream pipeline use
            "quantity_on_hand":    total_on_hand,
            "quantity_reserved":   total_reserved,
            "status":              primary.get("status", "ACTIVE"),
            "unit_cost":           primary.get("unit_cost", 0.0),
            "certificate_type":    primary.get("certificate_type", "None"),
            "has_full_trace":      has_full_trace,
        }
