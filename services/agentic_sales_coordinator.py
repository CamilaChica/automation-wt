from __future__ import annotations

from typing import Any

from services.procurement_service import ProcurementService, procurement_service
from services.sales_automation_service import SalesAutomationService, sales_automation_service


class AgenticSalesCoordinator:
    def __init__(
        self,
        *,
        sales_service: SalesAutomationService | None = None,
        procurement: ProcurementService | None = None,
    ):
        self.sales_service = sales_service or sales_automation_service
        self.procurement = procurement or procurement_service

    def run_rfq_cycle(self, rfq_id: str) -> dict[str, Any]:
        procurement_actions = self.procurement.trigger_out_of_stock_procurement(rfq_id)
        quote_outcome = self.sales_service.generate_customer_quote(rfq_id)
        return {
            "rfq_id": rfq_id,
            "procurement_actions": procurement_actions,
            "quote_outcome": quote_outcome,
        }


agentic_sales_coordinator = AgenticSalesCoordinator()
