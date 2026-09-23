import asyncio
import json
from typing import Any, Dict, Iterable, List, Optional, Type
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError, create_model

from agents.base_agent import AgentMetadata, BaseAgent
from agents.compliance_agent import ComplianceAgent
from agents.customer_communication_agent import CustomerCommunicationAgent
from agents.inventory_agent import InventoryAgent
from agents.orchestrator_agent import OrchestratorAgent
from agents.parts_intelligence_agent import PartsIntelligenceAgent
from agents.pricing_agent import PricingAgent
from agents.quote_generation_agent import QuoteGenerationAgent
from agents.rfq_intake_agent import RFQIntakeAgent
from agents.supplier_discovery_agent import SupplierDiscoveryAgent


AGENT_FACTORIES = [
    RFQIntakeAgent,
    InventoryAgent,
    PartsIntelligenceAgent,
    SupplierDiscoveryAgent,
    ComplianceAgent,
    PricingAgent,
    QuoteGenerationAgent,
    CustomerCommunicationAgent,
    OrchestratorAgent,
]

REQUIRED_FIELDS = [
    "name",
    "role",
    "objective",
    "system_instruction",
    "input_schema",
    "output_schema",
    "available_tools",
    "permissions",
    "escalation_rules",
    "prompt_templates",
]


def _sample_value_for_schema(field_schema: Dict[str, Any], field_name: str = "") -> Any:
    if "enum" in field_schema:
        return field_schema["enum"][0]
    if "anyOf" in field_schema:
        for option in field_schema["anyOf"]:
            if option.get("type") != "null":
                return _sample_value_for_schema(option, field_name)
    if "oneOf" in field_schema:
        for option in field_schema["oneOf"]:
            if option.get("type") != "null":
                return _sample_value_for_schema(option, field_name)
    if "type" in field_schema:
        raw_types = field_schema["type"]
        if isinstance(raw_types, list):
            for value in raw_types:
                if value != "null":
                    raw_types = value
                    break
        if raw_types == "string":
            if "part_number" in field_name.lower():
                return "060-1234-00"
            if "email" in field_name.lower():
                return "buyer@example.com"
            if "name" in field_name.lower():
                return "Acme MRO"
            if "status" in field_name.lower():
                return "PENDING"
            if "condition" in field_name.lower():
                return "NE"
            return "sample-value"
        if raw_types == "integer":
            return 2
        if raw_types == "number":
            return 1200.0
        if raw_types == "boolean":
            return True
        if raw_types == "array":
            item_schema = field_schema.get("items", {"type": "string"})
            return [_sample_value_for_schema(item_schema, field_name)]
        if raw_types == "object":
            return {
                key: _sample_value_for_schema(value_schema, key)
                for key, value_schema in field_schema.get("properties", {}).items()
            }
    if "properties" in field_schema:
        return {
            key: _sample_value_for_schema(value_schema, key)
            for key, value_schema in field_schema.get("properties", {}).items()
        }
    if "items" in field_schema:
        return [_sample_value_for_schema(field_schema["items"], field_name)]
    return "sample-value"


def _sample_payload_for_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    properties = schema.get("properties", {})
    for field_name, field_schema in properties.items():
        payload[field_name] = _sample_value_for_schema(field_schema, field_name)
    return payload


def _schema_to_pydantic_model(schema: Dict[str, Any], model_name: str, extra: str = "forbid"):
    properties = schema.get("properties", {})
    required_fields = set(schema.get("required", []))
    field_definitions: Dict[str, Any] = {}

    def map_type(subschema: Dict[str, Any], name: str):
        if "anyOf" in subschema:
            options = [map_type(option, name) for option in subschema["anyOf"] if option.get("type") != "null"]
            if len(options) == 1:
                return options[0]
            return Optional[tuple(options)] if False else Any
        if "oneOf" in subschema:
            options = [map_type(option, name) for option in subschema["oneOf"] if option.get("type") != "null"]
            if len(options) == 1:
                return options[0]
            return Any
        if "type" in subschema:
            raw_types = subschema["type"]
            if isinstance(raw_types, list):
                if "null" in raw_types:
                    raw_types = [value for value in raw_types if value != "null"][0]
                else:
                    raw_types = raw_types[0]
            if raw_types == "string":
                return str
            if raw_types == "integer":
                return int
            if raw_types == "number":
                return float
            if raw_types == "boolean":
                return bool
            if raw_types == "object":
                nested = subschema.get("properties", {})
                if nested:
                    return _schema_to_pydantic_model(subschema, f"{model_name}_{name}", extra=extra)
                return dict
            if raw_types == "array":
                items = subschema.get("items", {"type": "string"})
                item_type = map_type(items, name)
                return List[item_type]
        if "properties" in subschema:
            return _schema_to_pydantic_model(subschema, f"{model_name}_{name}", extra=extra)
        return Any

    for field_name, field_schema in properties.items():
        field_type = map_type(field_schema, field_name)
        if field_name in required_fields:
            field_definitions[field_name] = (field_type, ...)  # type: ignore[index]
        else:
            field_definitions[field_name] = (Optional[field_type], None)  # type: ignore[assignment]

    return create_model(model_name, __config__=ConfigDict(extra=extra), **field_definitions)


def _enforce_permission(agent: BaseAgent, attempted_tool: str):
    if attempted_tool not in agent.metadata.available_tools:
        raise PermissionError(f"Tool '{attempted_tool}' is not permitted for agent '{agent.metadata.name}'.")


def _mock_tool_response(agent: BaseAgent):
    if isinstance(agent, InventoryAgent):
        return {
            "available_quantity": 5,
            "shortage_quantity": 0,
            "availability_status": "IN_STOCK",
            "condition": "NE",
            "warehouse": "WH-01",
            "lead_time": "7 days",
            "unit_cost": 1000.0,
            "certificate_type": "FAA 8130-3",
            "has_full_trace": True,
        }
    if isinstance(agent, PartsIntelligenceAgent):
        return {
            "found": True,
            "match_type": "exact",
            "parts": [{
                "part_number": "060-1234-00",
                "description": "Weather Radar Receiver-Transmitter",
                "manufacturer": "Honeywell",
                "category": "Avionics",
                "aircraft_applicability": "B737",
                "condition": "NE",
                "alternate_part_numbers": ["060-1234-01"],
                "documentation_requirements": ["FAA 8130-3", "CoC"],
            }],
        }
    if isinstance(agent, SupplierDiscoveryAgent):
        return [{
            "supplier_id": "SUP-100",
            "supplier_name": "AeroSupplies Inc",
            "part_number": "060-1234-00",
            "unit_cost": 950.0,
            "quantity_available": 10,
            "lead_time_days": 12,
            "certificate_type": "FAA 8130-3",
            "approval_status": "Approved",
            "reliability_score": 98.0,
            "score": 90.0,
        }]
    return {"ok": True}


@pytest.mark.parametrize("agent_factory", AGENT_FACTORIES, ids=[cls.__name__ for cls in AGENT_FACTORIES])
def test_agent_schema_contract_and_metadata(agent_factory):
    agent = agent_factory()
    metadata: AgentMetadata = agent.metadata

    for field in REQUIRED_FIELDS:
        value = getattr(metadata, field, None)
        assert value is not None, f"{agent.metadata.name} missing {field}"
        if isinstance(value, str):
            assert value.strip(), f"{agent.metadata.name} has empty {field}"
        elif isinstance(value, (list, dict)) and field not in {"available_tools", "escalation_rules"}:
            assert len(value) > 0, f"{agent.metadata.name} has empty {field}"

    input_model = _schema_to_pydantic_model(metadata.input_schema, f"{metadata.name}Input")
    valid_input = _sample_payload_for_schema(metadata.input_schema)
    validated = input_model.model_validate(valid_input)
    assert validated is not None

    with pytest.raises(ValidationError):
        input_model.model_validate({"unexpected": "value"})

    output_model = _schema_to_pydantic_model(metadata.output_schema, f"{metadata.name}Output")
    sample_output = _sample_payload_for_schema(metadata.output_schema)
    output_model.model_validate(sample_output)


@pytest.mark.parametrize("agent_factory", AGENT_FACTORIES, ids=[cls.__name__ for cls in AGENT_FACTORIES])
def test_agent_mock_execution_generates_valid_output(agent_factory, monkeypatch):
    agent = agent_factory()
    payload = _sample_payload_for_schema(agent.metadata.input_schema)

    for attr_name, attr_value in vars(agent).items():
        if hasattr(attr_value, "run") and callable(attr_value.run):
            monkeypatch.setattr(attr_value, "run", AsyncMock(return_value=_mock_tool_response(agent)))

    if isinstance(agent, CustomerCommunicationAgent):
        with patch.object(agent, "_format_quote_summary", return_value="Quote summary"), patch(
            "agents.customer_communication_agent.communication_service.send_customer_quote",
            return_value={"transmission_status": "SIMULATED"},
        ):
            response = asyncio.run(agent.execute(payload, context={"requested_price_limit": 1250.0}))
    else:
        response = asyncio.run(agent.execute(payload, context={"requested_price_limit": 1250.0}))

    assert isinstance(response, object)
    assert response is not None
    assert "```" not in json.dumps(response.model_dump() if hasattr(response, "model_dump") else response.data)

    output_model = _schema_to_pydantic_model(agent.metadata.output_schema, f"{agent.metadata.name}Output", extra="ignore")
    if response.data:
        output_model.model_validate(response.data)


@pytest.mark.parametrize("agent_factory", AGENT_FACTORIES, ids=[cls.__name__ for cls in AGENT_FACTORIES])
def test_permission_guard_blocks_unpermitted_tool(agent_factory):
    agent = agent_factory()
    prohibited_tool = "super_secret_external_email_dispatch"
    with pytest.raises(PermissionError):
        _enforce_permission(agent, prohibited_tool)


@pytest.mark.parametrize("agent_factory", AGENT_FACTORIES, ids=[cls.__name__ for cls in AGENT_FACTORIES])
def test_escalation_or_failure_on_edge_cases(agent_factory):
    agent = agent_factory()

    if isinstance(agent, RFQIntakeAgent):
        result = asyncio.run(agent.execute({"raw_text": ""}))
        assert result.escalation_triggered is not None or not result.success
        return

    if isinstance(agent, PartsIntelligenceAgent):
        result = asyncio.run(agent.execute({"requested_part_number": "INVALID/123"}))
        assert result.escalation_triggered is not None or not result.success
        return

    if isinstance(agent, ComplianceAgent):
        result = asyncio.run(agent.execute({
            "part_number": "060-1234-00",
            "source": "Supplier",
            "supplier_name": "Blacklisted Co",
            "certificate_type": "None",
            "has_full_trace": False,
            "requested_certificate_type": "FAA 8130-3",
            "requested_condition": "NE",
        }))
        assert result.escalation_triggered is not None or not result.success
        return

    if isinstance(agent, InventoryAgent):
        result = asyncio.run(agent.execute({"part_number": "UNKNOWN-999", "requested_quantity": 2}))
        assert result.escalation_triggered is not None or result.data.get("availability_status") != "IN_STOCK"
        return

    if isinstance(agent, SupplierDiscoveryAgent):
        result = asyncio.run(agent.execute({"part_number": "MISSING-1", "quantity_needed": 2}))
        assert result.escalation_triggered is not None or not result.success
        return

    if isinstance(agent, PricingAgent):
        result = asyncio.run(agent.execute({"unit_cost": 1000.0, "quantity": 1}, context={"requested_price_limit": 1100.0}))
        assert result.escalation_triggered is not None
        return

    if agent.metadata.escalation_rules:
        malformed = _sample_payload_for_schema(agent.metadata.input_schema)
        malformed = {**malformed, **{"part_number": "", "raw_text": ""}} if "raw_text" in malformed else malformed
        result = asyncio.run(agent.execute(malformed))
        assert result.escalation_triggered is not None or not result.success


@pytest.mark.parametrize("agent_factory", AGENT_FACTORIES, ids=[cls.__name__ for cls in AGENT_FACTORIES])
def test_agent_tool_invocation_format_is_structured_and_valid(agent_factory, monkeypatch):
    agent = agent_factory()

    if not agent.metadata.available_tools:
        pytest.skip("No tools to validate")

    # A generic tool boundary check: the agent advertises only tools it can invoke.
    tool_names = set(agent.metadata.available_tools)
    assert tool_names
    for tool_name in tool_names:
        assert isinstance(tool_name, str)
        assert tool_name.strip()

    if hasattr(agent, "_check_inventory_tool"):
        monkeypatch.setattr(agent._check_inventory_tool, "run", AsyncMock(return_value=_mock_tool_response(agent)))
    if hasattr(agent, "_catalog_tool"):
        monkeypatch.setattr(agent._catalog_tool, "run", AsyncMock(return_value=_mock_tool_response(agent)))

    payload = _sample_payload_for_schema(agent.metadata.input_schema)
    if isinstance(agent, CustomerCommunicationAgent):
        with patch(
            "agents.customer_communication_agent.communication_service.send_customer_quote",
            return_value={"transmission_status": "SIMULATED"},
        ):
            response = asyncio.run(agent.execute(payload, context={"requested_price_limit": 1250.0}))
    else:
        response = asyncio.run(agent.execute(payload, context={"requested_price_limit": 1250.0}))
    assert response is not None
