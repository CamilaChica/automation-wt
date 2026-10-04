import asyncio

from agents import AGENT_CONFIGS
from agents.compliance_agent import ComplianceAgent
from agents.customer_communication_agent import CustomerCommunicationAgent
from agents.inventory_agent import InventoryAgent
from agents.orchestrator_agent import OrchestratorAgent
from agents.parts_intelligence_agent import PartsIntelligenceAgent
from agents.pricing_agent import PricingAgent
from agents.quote_generation_agent import QuoteGenerationAgent
from agents.rfq_intake_agent import RFQIntakeAgent
from agents.supplier_discovery_agent import SupplierDiscoveryAgent


def test_all_agents_receive_lifecycle_tuning_and_runtime_configuration():
    agents = [
        RFQIntakeAgent(),
        PartsIntelligenceAgent(),
        InventoryAgent(),
        SupplierDiscoveryAgent(),
        ComplianceAgent(),
        PricingAgent(),
        QuoteGenerationAgent(),
        CustomerCommunicationAgent(),
        OrchestratorAgent(),
    ]

    assert len(agents) == 9
    assert all("Fine-tuned runtime guidance:" in agent.metadata.system_instruction for agent in agents)
    assert {agent.metadata.name for agent in agents} == set(AGENT_CONFIGS)
    for agent in agents:
        config = AGENT_CONFIGS[agent.metadata.name]
        assert agent.metadata.available_tools == config["tools"]
        assert "request_supplier_discount" in {
            contract["name"] for contract in agent.metadata.available_tool_contracts
        }
        assert config["system_instructions"] in agent.metadata.system_instruction
        assert agent.metadata.llm_profile.model == config["model"]
        assert agent.metadata.llm_profile.temperature == config["temperature"]
        assert agent.metadata.llm_profile.max_tokens == config["max_tokens"]
        assert agent.metadata.llm_profile.response_format == "json"
        assert agent.metadata.error_fallback == config["error_fallback"]


def test_supplier_discount_contract_is_metadata_for_every_agent():
    expected = AGENT_CONFIGS["RFQIntakeAgent"]["tool_contracts"][0]
    assert all(
        config["tool_contracts"][0] == expected
        for config in AGENT_CONFIGS.values()
    )
    assert expected["permission_tier"] == "Tier_2"
    assert expected["idempotency_required"] is True
    assert expected["rate_limit_seconds"] == 60
    assert expected["audit_logging"] is True
    assert expected["parameters"]["required"] == [
        "supplier_id",
        "part_number",
        "target_discount_percentage",
        "currency",
    ]


def test_agent_failure_uses_configured_fallback():
    inventory_response = InventoryAgent().handle_escalation({}, "inventory lookup failed")
    customer_response = CustomerCommunicationAgent().handle_escalation({}, "draft failed")

    assert inventory_response.escalation_triggered.escalate_to == "orchestrator"
    assert inventory_response.escalation_triggered.action == "route_to_orchestrator"
    assert customer_response.escalation_triggered.escalate_to == "human_operator"


def test_pricing_escalates_below_autonomous_margin_threshold():
    async def run():
        result = await PricingAgent().execute(
            {"unit_cost": 1000.0, "quantity": 1},
            context={"requested_price_limit": 1219.0},
        )
        assert result.success is True
        assert result.data["margin_percent"] < 18.0
        assert result.escalation_triggered is not None

    asyncio.run(run())
