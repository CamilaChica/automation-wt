import unittest

from agents.base_agent import BaseAgent, AgentMetadata, ConfigurationError
from agents.inventory_agent import InventoryAgent


class TestAgentContract(unittest.TestCase):
    def test_base_agent_rejects_incomplete_contract(self):
        invalid = AgentMetadata(
            name="BadAgent",
            role="Test",
            objective="Test objective",
            system_instruction="Follow the rules.",
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object", "properties": {}},
            available_tools=["tool_a"],
            permissions=["read"],
            escalation_rules=[],
        )
        invalid.permissions = None

        with self.assertRaises(ConfigurationError):
            BaseAgent(invalid)

    def test_inventory_agent_has_strict_contract(self):
        agent = InventoryAgent()
        metadata = agent.metadata

        self.assertEqual(metadata.name, "InventoryAgent")
        self.assertTrue(metadata.system_instruction)
        self.assertIn("default", metadata.prompt_templates)
        self.assertTrue(metadata.available_tools)
        self.assertTrue(metadata.permissions)
        self.assertTrue(metadata.escalation_rules)


if __name__ == "__main__":
    unittest.main()
