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

    def test_client_quotes_round_up_from_50_to_50(self):
        # 100 / 0.8 = 125.0 -> rounded up to 150.0
        res1 = asyncio.run(PricingAgent().execute({"unit_cost": 100.0, "quantity": 1}))
        self.assertEqual(res1.data["suggested_unit_price"], 150.0)
        self.assertEqual(res1.data["suggested_unit_price"] % 50.0, 0.0)

        # 125 / 0.8 = 156.25 -> rounded up to 200.0
        res2 = asyncio.run(PricingAgent().execute({"unit_cost": 125.0, "quantity": 1}))
        self.assertEqual(res2.data["suggested_unit_price"], 200.0)
        self.assertEqual(res2.data["suggested_unit_price"] % 50.0, 0.0)

        # Small cost: 15 / 0.8 = 18.75 -> rounded up to 50.0
        res3 = asyncio.run(PricingAgent().execute({"unit_cost": 15.0, "quantity": 1}))
        self.assertEqual(res3.data["suggested_unit_price"], 50.0)
        self.assertEqual(res3.data["suggested_unit_price"] % 50.0, 0.0)

        # Bulk qty 10 (15% margin): 1000 / 0.85 = 1176.47 -> rounded up to 1200.0
        res4 = asyncio.run(PricingAgent().execute({"unit_cost": 1000.0, "quantity": 10}))
        self.assertEqual(res4.data["suggested_unit_price"], 1200.0)
        self.assertEqual(res4.data["suggested_unit_price"] % 50.0, 0.0)

        # Qty 5 (18% margin): 1000 / 0.82 = 1219.51 -> rounded up to 1250.0
        res5 = asyncio.run(PricingAgent().execute({"unit_cost": 1000.0, "quantity": 5}))
        self.assertEqual(res5.data["suggested_unit_price"], 1250.0)
        self.assertEqual(res5.data["suggested_unit_price"] % 50.0, 0.0)

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
