"""Agent package and runtime configuration for the RFQ-to-quote system."""

SUPPLIER_DISCOUNT_TOOL_CONTRACT = {
    "name": "request_supplier_discount",
    "description": (
        "Queue one non-binding request for an approved supplier to consider a discount "
        "of up to 5% on a verified USD offer. It cannot accept an offer or place an order."
    ),
    "permission_tier": "Tier_2",
    "idempotency_required": True,
    "parameters": {
        "type": "object",
        "properties": {
            "supplier_id": {
                "type": "string",
                "description": "Persisted identifier for the approved supplier.",
            },
            "part_number": {
                "type": "string",
                "description": "Exact part number on the supplier's approved offer.",
            },
            "target_discount_percentage": {
                "type": "number",
                "description": "Requested discount from the verified offer price; greater than 0 and no more than 5%.",
            },
            "currency": {
                "type": "string",
                "enum": ["USD"],
                "description": "USD only; non-USD offers are not eligible for automated discount requests.",
            },
        },
        "required": [
            "supplier_id",
            "part_number",
            "target_discount_percentage",
            "currency",
        ],
        "additionalProperties": False,
    },
    "rate_limit_seconds": 60,
    "audit_logging": True,
}

AGENT_CONFIGS = {
    "RFQIntakeAgent": {
        "agent_name": "RFQIntakeAgent",
        "model": None,
        "temperature": 0.0,
        "max_tokens": 1800,
        "system_instructions": (
            "Extract only facts present in the RFQ. Preserve part, quantity, condition, "
            "urgency, and delivery details; flag ambiguity instead of guessing."
        ),
        "tools": [],
        "output_format": "json_schema",
        "error_fallback": "escalate_to_human_queue",
    },
    "PartsIntelligenceAgent": {
        "agent_name": "PartsIntelligenceAgent",
        "model": None,
        "temperature": 0.0,
        "max_tokens": 1200,
        "system_instructions": (
            "Use persisted inventory and supplier-offer evidence only. Return exact "
            "part-number matches; never infer product details or interchangeability."
        ),
        "tools": ["search_parts_catalog"],
        "output_format": "json_schema",
        "error_fallback": "escalate_to_human_queue",
    },
    "InventoryAgent": {
        "agent_name": "InventoryAgent",
        "model": None,
        "temperature": 0.0,
        "max_tokens": 1000,
        "system_instructions": (
            "Report confirmed available-to-promise stock only. Route shortages and "
            "unknown parts to supplier sourcing."
        ),
        "tools": ["check_inventory"],
        "output_format": "json_schema",
        "error_fallback": "route_to_orchestrator",
    },
    "SupplierDiscoveryAgent": {
        "agent_name": "SupplierDiscoveryAgent",
        "model": None,
        "temperature": 0.0,
        "max_tokens": 1600,
        "system_instructions": (
            "Use current, dated supplier offers. Preserve source references and reject "
            "stale, insufficient, unapproved, or untraceable offers."
        ),
        "tools": ["supplier_network_search"],
        "output_format": "json_schema",
        "error_fallback": "escalate_to_human_queue",
    },
    "ComplianceAgent": {
        "agent_name": "ComplianceAgent",
        "model": None,
        "temperature": 0.0,
        "max_tokens": 1400,
        "system_instructions": (
            "Treat missing or conflicting trace, certificate, supplier approval, and "
            "export-control evidence as blocking or requiring human review."
        ),
        "tools": ["regulatory_checklist_lookup"],
        "output_format": "json_schema",
        "error_fallback": "escalate_to_human_queue",
    },
    "PricingAgent": {
        "agent_name": "PricingAgent",
        "model": None,
        "temperature": 0.0,
        "max_tokens": 1000,
        "system_instructions": (
            "Calculate prices deterministically from approved costs and margin policy. "
            "Do not conceal shipping or bypass low-margin approval."
        ),
        "tools": ["margin_calculator"],
        "output_format": "json_schema",
        "error_fallback": "escalate_to_human_queue",
    },
    "QuoteGenerationAgent": {
        "agent_name": "QuoteGenerationAgent",
        "model": None,
        "temperature": 0.0,
        "max_tokens": 1800,
        "system_instructions": (
            "Preserve approved line-item details, verify totals, exclude unquoted "
            "shipping, and keep the quote pending required human approval."
        ),
        "tools": ["document_renderer"],
        "output_format": "json_schema",
        "error_fallback": "escalate_to_human_queue",
    },
    "CustomerCommunicationAgent": {
        "agent_name": "CustomerCommunicationAgent",
        "model": None,
        "temperature": 0.2,
        "max_tokens": 1500,
        "system_instructions": (
            "Draft clear, professional customer messages from approved quote data only. "
            "Never send an unapproved or compliance-blocked quote."
        ),
        "tools": ["email_sender_service", "llm_provider"],
        "output_format": "json_schema",
        "error_fallback": "escalate_to_human_queue",
    },
    "OrchestratorAgent": {
        "agent_name": "OrchestratorAgent",
        "model": None,
        "temperature": 0.0,
        "max_tokens": 2400,
        "system_instructions": (
            "Coordinate bounded, authorized analysis only. Stop on missing evidence, "
            "policy blocks, or approval gates; never claim an action without confirmation. "
            "Supplier discount requests are non-binding, limited to approved USD offers, "
            "and capped at a 5% requested discount."
        ),
        "tools": [
            "lookup_part",
            "check_inventory",
            "search_suppliers",
            "calculate_price",
            "query_rfq",
            "query_supplier_offers",
            "search_knowledge",
            "request_supplier_discount",
        ],
        "output_format": "json_schema",
        "error_fallback": "escalate_to_human_queue",
    },
}

for _agent_config in AGENT_CONFIGS.values():
    _agent_config["tool_contracts"] = [SUPPLIER_DISCOUNT_TOOL_CONTRACT]
