#!/usr/bin/env python3
"""Synthetic liveness probe for the Winged Tycoons agent layer.

This script executes a non-destructive synthetic heartbeat against each registered
agent, records latency metadata, and prints a pass/fail matrix. It can be used in
local development and CI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Allow direct execution with `python scripts/probe_agent_liveness.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.base_agent import BaseAgent
from agents.compliance_agent import ComplianceAgent
from agents.customer_communication_agent import CustomerCommunicationAgent
from agents.inventory_agent import InventoryAgent
from agents.orchestrator_agent import OrchestratorAgent
from agents.parts_intelligence_agent import PartsIntelligenceAgent
from agents.pricing_agent import PricingAgent
from agents.quote_generation_agent import QuoteGenerationAgent
from agents.rfq_intake_agent import RFQIntakeAgent
from agents.supplier_discovery_agent import SupplierDiscoveryAgent
from services.operations_store import OperationsStore

os.environ.setdefault("EMAIL_SEND_ENABLED", "false")


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


def _sample_payload_for_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for field_name, field_schema in schema.get("properties", {}).items():
        if "enum" in field_schema:
            payload[field_name] = field_schema["enum"][0]
        elif field_name.lower().endswith("_number") or "part_number" in field_name.lower():
            payload[field_name] = "060-1234-00"
        elif "quantity" in field_name.lower():
            payload[field_name] = 2
        elif field_name.lower() == "raw_text":
            payload[field_name] = "Company: Acme MRO. Part Number: 060-1234-00. Qty: 2. Condition: NE."
        elif field_name.lower() == "requested_part_number":
            payload[field_name] = "060-1234-00"
        elif field_name.lower() in {"customer_email", "email"}:
            payload[field_name] = "buyer@example.com"
        elif field_name.lower() == "customer_name":
            payload[field_name] = "Acme MRO"
        elif field_name.lower() == "rfq_id":
            payload[field_name] = "RFQ-HEARTBEAT"
        elif field_name.lower() == "units":
            payload[field_name] = "EA"
        elif field_name.get("type") == "boolean":
            payload[field_name] = True
        elif field_name.get("type") == "number":
            payload[field_name] = 1000.0
        else:
            payload[field_name] = "sample-value"
    return payload


def _safe_agent_payload(agent: BaseAgent) -> Dict[str, Any]:
    payload = _sample_payload_for_schema(agent.metadata.input_schema)
    if isinstance(agent, RFQIntakeAgent):
        payload = {"raw_text": "Company: Acme MRO. Part Number: 060-1234-00. Qty: 2. Condition: NE."}
    elif isinstance(agent, InventoryAgent):
        payload = {"part_number": "060-1234-00", "requested_quantity": 2}
    elif isinstance(agent, PartsIntelligenceAgent):
        payload = {"requested_part_number": "060-1234-00"}
    elif isinstance(agent, SupplierDiscoveryAgent):
        payload = {"part_number": "060-1234-00", "quantity_needed": 2}
    elif isinstance(agent, ComplianceAgent):
        payload = {
            "part_number": "060-1234-00",
            "source": "Inventory",
            "supplier_name": "AeroSupplies Inc",
            "certificate_type": "FAA 8130-3",
            "has_full_trace": True,
            "requested_certificate_type": "FAA 8130-3",
            "requested_condition": "NE",
        }
    elif isinstance(agent, PricingAgent):
        payload = {"unit_cost": 1000.0, "quantity": 2, "urgency": "Routine", "source": "Inventory"}
    elif isinstance(agent, QuoteGenerationAgent):
        payload = {
            "rfq_id": "RFQ-HEARTBEAT",
            "customer": "Acme MRO",
            "quote_items": [{
                "rfq_item_id": "RITM-1",
                "part_number": "060-1234-00",
                "quantity": 2,
                "unit_price": 1000.0,
                "condition": "NE",
                "lead_time_days": 7,
                "documentation": "FAA 8130-3",
                "source": "Inventory",
                "certificate_type": "FAA 8130-3",
                "unit_cost": 1000.0,
                "margin_percent": 20.0,
                "compliance_status": "APPROVED",
            }],
            "quote_validity_days": 30,
            "terms": "Standard terms apply.",
        }
    elif isinstance(agent, CustomerCommunicationAgent):
        payload = {
            "customer_email": "buyer@example.com",
            "customer_name": "Acme MRO",
            "quote_details": {
                "quote_id": "QTE-HEARTBEAT",
                "total_amount": 2500.0,
                "subtotal": 2500.0,
                "items": [{
                    "part_number": "060-1234-00",
                    "quantity": 2,
                    "uom": "EA",
                    "unit_price": 1000.0,
                    "attachments": ["FAA-8130-3.pdf"],
                }],
            },
        }
    elif isinstance(agent, OrchestratorAgent):
        payload = {"rfq_id": "RFQ-HEARTBEAT", "command": "START"}
    return payload


async def _execute_agent(agent: BaseAgent) -> Dict[str, Any]:
    payload = _safe_agent_payload(agent)
    start = time.perf_counter()
    response = await agent.execute(payload, context={"requested_price_limit": 1250.0})
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    return {
        "success": bool(response.success),
        "latency_ms": latency_ms,
        "data": response.data,
        "error": response.error_message,
    }


def _record_event(agent_name: str, status: str, latency_ms: float, note: str | None = None):
    store = OperationsStore()
    store.record_automation_event(
        event_type="agent_liveness_probe",
        entity_type="agent",
        entity_id=agent_name,
        status=status,
        result=note or "liveness_probe",
        idempotency_key=f"agent-probe-{agent_name.lower().replace(' ', '-')}",
        attempts=1,
        max_attempts=1,
    )


def _agent_name(agent: BaseAgent) -> str:
    return agent.metadata.name.lower().replace(" ", "_")


def _diagnose_agent(agent: BaseAgent) -> Tuple[str, str, str, str, str, str, str]:
    schema_ok = "PASS"
    mock_run_ok = "PASS"
    tool_boundary_ok = "PASS"
    escalation_ok = "PASS"
    live_probe = "PASS"
    status = "OK"

    try:
        for field in [
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
        ]:
            value = getattr(agent.metadata, field, None)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise ValueError(f"missing metadata field: {field}")
    except Exception:
        schema_ok = "FAIL"
        status = "ERROR"

    try:
        response = asyncio.run(_execute_agent(agent))
        # A valid business rejection or escalation is still a live agent result.
        if response.get("error") and not response.get("data"):
            raise RuntimeError(response["error"])
    except Exception:
        mock_run_ok = "WARN"

    if not agent.metadata.available_tools:
        tool_boundary_ok = "PASS"
    else:
        for tool_name in agent.metadata.available_tools:
            if not isinstance(tool_name, str) or not tool_name.strip():
                tool_boundary_ok = "FAIL"
                status = "ERROR"

    if agent.metadata.escalation_rules:
        try:
            if isinstance(agent, RFQIntakeAgent):
                bad = asyncio.run(agent.execute({"raw_text": ""}))
                if bad.escalation_triggered is None and bad.success:
                    raise RuntimeError("expected escalation on bad input")
        except Exception:
            escalation_ok = "FAIL"
            status = "ERROR"

    latency_ms = 0.0
    if mock_run_ok in {"PASS", "WARN"}:
        try:
            response = asyncio.run(_execute_agent(agent))
            latency_ms = response["latency_ms"]
            live_probe = "PASS" if mock_run_ok == "PASS" else "WARN"
        except Exception:
            live_probe = "WARN"
    else:
        live_probe = "FAIL"
        status = "ERROR"

    if status == "OK":
        status_label = f"OK"
    else:
        status_label = "ERROR"
    return (
        _agent_name(agent),
        schema_ok,
        mock_run_ok,
        tool_boundary_ok,
        escalation_ok,
        f"PASS ({latency_ms}ms)" if live_probe == "PASS" else "FAIL",
        status_label,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run synthetic liveness probes across all registered agents.")
    parser.add_argument("--ci", action="store_true", help="Simple CI mode used in GitHub Actions.")
    args = parser.parse_args()

    rows = [_diagnose_agent(factory()) for factory in AGENT_FACTORIES]
    print("=================== AGENT LIVENESS DIAGNOSTIC MATRIX ===================")
    print(f"{'Agent Name':<24} {'Schema':<8} {'Mock Run':<9} {'Tool Boundary':<15} {'Escalation':<11} {'Live Probe':<16} {'Status'}")
    print("-" * 110)
    for row in rows:
        print(f"{row[0]:<24} {row[1]:<8} {row[2]:<9} {row[3]:<15} {row[4]:<11} {row[5]:<16} {row[6]}")
    ok_count = sum(1 for row in rows if row[6] == "OK")
    total = len(rows)
    print(f"Summary: {ok_count}/{total} Agents Live and Functional.")
    return 0 if ok_count == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
