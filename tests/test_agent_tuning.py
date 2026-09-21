import asyncio

from agents.compliance_agent import ComplianceAgent
from agents.customer_communication_agent import CustomerCommunicationAgent
from agents.inventory_agent import InventoryAgent
from agents.orchestrator_agent import OrchestratorAgent
from agents.parts_intelligence_agent import PartsIntelligenceAgent
from agents.pricing_agent import PricingAgent
from agents.quote_generation_agent import QuoteGenerationAgent
from agents.rfq_intake_agent import RFQIntakeAgent
from agents.supplier_discovery_agent import SupplierDiscoveryAgent


def test_all_agents_receive_lifecycle_tuning_guidance():
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
