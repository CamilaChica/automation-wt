"""Deterministic pricing, margin, and currency safety gates."""

import asyncio
import unittest

from agents.pricing_agent import NegativeMarginError, PricingAgent


class TestFinancialEdgeCases(unittest.TestCase):
    def test_standard_pricing_is_deterministic(self):
        first = asyncio.run(PricingAgent().execute({"unit_cost": 1000.0, "quantity": 1}))
        second = asyncio.run(PricingAgent().execute({"unit_cost": 1000.0, "quantity": 1}))

        self.assertEqual(first.data, second.data)
        self.assertEqual(first.data["suggested_unit_price"], 1250.0)
        self.assertGreater(first.data["margin_percent"], 0)

    def test_low_margin_triggers_escalation(self):
        result = asyncio.run(PricingAgent().execute({
            "unit_cost": 1000.0,
            "quantity": 1,
            "requested_price_limit": 1001.0,
        }, context={"requested_price_limit": 1001.0}))

        self.assertTrue(result.success)
        self.assertLess(result.data["margin_percent"], 10.0)
        self.assertEqual(result.escalation_triggered.condition, "margin_below_threshold")

    def test_negative_margin_must_halt_with_domain_error(self):
        with self.assertRaises(NegativeMarginError):
            asyncio.run(PricingAgent().execute({
                "unit_cost": 1000.0,
                "quantity": 1,
            }, context={"requested_price_limit": 900.0}))

    @unittest.skip("Currency conversion, frozen exchange-rate storage, tax, hazmat, and wire fees are not implemented.")
    def test_currency_and_fee_components_are_persisted(self):
        pass


if __name__ == "__main__":
    unittest.main()
