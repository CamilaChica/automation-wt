from typing import Dict, Any, Optional, List, Tuple
import datetime
from agents.base_agent import BaseAgent, AgentMetadata, AgentResponse, EscalationRule

class ComplianceAgent(BaseAgent):
    # Mock documentation records (in lieu of a real database)
    MOCK_DOCUMENTS: List[Dict[str, Any]] = [
        {
            "part_number": "PN-001",
            "supplier_name": "AeroSupplies Inc",
            "certificate_type": "FAA 8130-3",
            "certificate_status": "valid",
            "expiration_date": "2025-12-31",
            "trace_complete": True,
            "supplier_approved": True,
        },
        {
            "part_number": "PN-002",
            "supplier_name": "AeroSupplies Inc",
            "certificate_type": "EASA Form 1",
            "certificate_status": "expired",
            "expiration_date": "2022-06-30",
            "trace_complete": True,
            "supplier_approved": True,
        },
        {
            "part_number": "PN-003",
            "supplier_name": "Blacklisted Co",
            "certificate_type": "FAA 8130-3",
            "certificate_status": "valid",
            "expiration_date": "2024-08-15",
            "trace_complete": False,
            "supplier_approved": False,
        },
    ]

    def __init__(self):
        metadata = AgentMetadata(
            name="ComplianceAgent",
            role="Aviation Compliance & Quality Assurance Auditor",
            objective="Inspect part pedigree, trace documentation, and supplier regulatory compliance.",
            system_instructions=(
                "You audit part sources. Check certificate presence (e.g., FAA Form 8130-3, EASA Form 1). "
                "Verify trace logs are intact. Flag unvetted suppliers or safety warnings. "
                "If critical documents are missing or risk levels are high, halt for review."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "part_number": {"type": "string"},
                    "source": {"type": "string", "enum": ["Inventory", "Supplier"]},
                    "supplier_name": {"type": "string"},
                    "certificate_type": {"type": "string"},
                    "has_full_trace": {"type": "boolean"}
                },
                "required": ["part_number", "source", "certificate_type"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "compliance_status": {"type": "string", "enum": ["APPROVED", "REJECTED", "HUMAN_REVIEW_REQUIRED"]},
                    "issues_detected": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["compliance_status", "issues_detected"]
            },
            available_tools=["regulatory_checklist_lookup"],
            permissions=["verify_compliance"],
            escalation_rules=[
                EscalationRule(
                    condition="compliance_failure",
                    action="halt_for_review",
                    escalate_to="human_operator"
                ),
                EscalationRule(
                    condition="missing_airworthiness_certificate",
                    action="halt_for_review",
                    escalate_to="human_operator"
                )
            ]
        )
        super().__init__(metadata)

    async def execute(self, inputs: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        part_number = inputs.get("part_number", "")
        source = inputs.get("source", "Inventory")
        supplier_name = inputs.get("supplier_name", "")
        cert_type = inputs.get("certificate_type", "None")
        has_trace = inputs.get("has_full_trace", True)
        
        issues = []
        trace_issue = False
        # Retrieve mock document record for the part
        record = next((doc for doc in self.MOCK_DOCUMENTS if doc["part_number"] == part_number), None)
        if not record:
            # Check if this part number is one of our standard inventory/supplier parts
            if part_number in ["060-1234-00", "456-789-OH"]:
                unapproved = ["Suspect Supplier Corp", "Blacklisted Co", "Blacklist Spares"]
                if supplier_name in unapproved:
                    issues.append(f"Supplier '{supplier_name}' is not approved.")
                
                valid_certs = ["FAA 8130-3", "EASA Form 1", "CoC"]
                if cert_type not in valid_certs or cert_type == "None":
                    issues.append(f"Missing valid airworthiness certificate (got '{cert_type}').")
                    
                if not has_trace:
                    issues.append("Incomplete traceability information.")
                    trace_issue = True
            else:
                issues.append(f"No documentation found for part number {part_number}.")
        else:
            # Supplier approval check
            if not record.get("supplier_approved", False):
                issues.append(f"Supplier '{record['supplier_name']}' is not approved.")
            # Certificate type and status
            if record["certificate_type"] != cert_type:
                issues.append(f"Certificate type mismatch: expected {record['certificate_type']}, got {cert_type}.")
            if record["certificate_status"] != "valid":
                issues.append(f"Certificate status is {record['certificate_status']}, not valid.")
            # Expiration check
            if record["expiration_date"] < "2023-01-01":
                issues.append("Certificate has expired.")
            # Traceability check
            if not record.get("trace_complete", False):
                issues.append("Incomplete traceability information.")
                trace_issue = True
        
        # Determine final compliance status based on gathered issues
        if not issues:
            compliance_status = "APPROVED"
        elif trace_issue and len(issues) == 1:
            compliance_status = "HUMAN_REVIEW_REQUIRED"
        else:
            compliance_status = "REJECTED"

        # Set escalation for trace issues as warning
        escalation = None
        if trace_issue:
            escalation = self.metadata.escalation_rules[1]

        response_data = {
            "compliance_status": compliance_status,
            "issues_detected": issues
        }
        # Success is true for APPROVED or HUMAN_REVIEW_REQUIRED (warnings allow continuation to human review state)
        success = compliance_status != "REJECTED"
        return AgentResponse(
            success=success,
            data=response_data,
            error_message=None if success else f"Compliance check failed for {part_number}: " + ", ".join(issues),
            escalation_triggered=escalation
        )
