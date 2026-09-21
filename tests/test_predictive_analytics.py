import unittest

from services.predictive_analytics import (
    DemandRiskInput,
    SupplierReliabilityInput,
    score_demand_risk,
    score_supplier_reliability,
)


class TestPredictiveAnalytics(unittest.TestCase):
    def test_reliable_supplier_gets_low_risk(self):
        result = score_supplier_reliability(SupplierReliabilityInput(
            completed_orders=20,
            on_time_deliveries=19,
            returns=0,
            average_lead_time_days=4,
            lead_time_variance_days=1,
        ))

        self.assertEqual(result.risk_level, "LOW")
        self.assertGreaterEqual(result.score, 80)
        self.assertEqual(result.confidence, 1.0)

    def test_unknown_supplier_is_low_confidence(self):
        result = score_supplier_reliability(SupplierReliabilityInput())

        self.assertEqual(result.confidence, 0.0)
        self.assertIn("No completed order history", result.reasons[0])

    def test_scarce_aog_demand_recommends_pre_sourcing(self):
        result = score_demand_risk(DemandRiskInput(
            requests_last_30_days=10,
            aog_requests_last_30_days=5,
            requested_quantity_last_30_days=20,
            available_quantity=2,
            active_supplier_count=1,
            average_lead_time_days=21,
        ))

        self.assertEqual(result.risk_level, "HIGH")
        self.assertEqual(result.recommended_action, "ESCALATE_AND_PRE_SOURCE")

    def test_balanced_supply_is_monitor_only(self):
        result = score_demand_risk(DemandRiskInput(
            requests_last_30_days=4,
            aog_requests_last_30_days=0,
            requested_quantity_last_30_days=4,
            available_quantity=10,
            active_supplier_count=5,
            average_lead_time_days=3,
        ))

        self.assertEqual(result.risk_level, "LOW")
        self.assertEqual(result.recommended_action, "MONITOR")


if __name__ == "__main__":
    unittest.main()
