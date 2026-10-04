from typing import Dict, Any, Optional
import datetime
from agents.base_agent import BaseAgent, AgentMetadata, AgentResponse, EscalationRule
from services.agents.prompts import COMPLIANCE_PROMPT

class ComplianceAgent(BaseAgent):
    def __init__(self):
        metadata = AgentMetadata(
            name="ComplianceAgent",
            role="Aviation Compliance & Quality Assurance Auditor",
            objective="Inspect part pedigree, trace documentation, and supplier regulatory compliance.",
            system_instruction=COMPLIANCE_PROMPT,
            input_schema={
                "type": "object",
                "properties": {
                    "part_number": {"type": "string"},
                    "source": {"type": "string", "enum": ["Inventory", "Supplier"]},
                    "supplier_name": {"type": "string"},
                    "certificate_type": {"type": "string"},
                    "has_full_trace": {"type": "boolean"},
                    "trace_documents": {"type": "array", "items": {"type": "string"}},
                    "supplier_approved": {"type": "boolean"},
                    "certificate_status": {"type": "string"},
                    "expiration_date": {"type": "string"},
                    "requested_certificate_type": {"type": "string"},
                    "requested_condition": {"type": "string"}
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
            ],
            prompt_templates={
                "default": "You audit part sources. Check certificate presence (e.g., FAA Form 8130-3, EASA Form 1). Verify trace logs are intact. Flag unvetted suppliers or safety warnings. If critical documents are missing or risk levels are high, halt for review.",
                "compliance_check": "Inspect the part certificate, trace record, and supplier approval before continuing.",
            }
        )
        super().__init__(metadata)

    async def execute(self, inputs: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        part_number = inputs.get("part_number", "")
        source = inputs.get("source", "Inventory")
        supplier_name = inputs.get("supplier_name", "")
        cert_type = inputs.get("certificate_type", "None")
        has_trace = inputs.get("has_full_trace") is True
        raw_trace_documents = inputs.get("trace_documents")
        trace_documents = (
            [document for document in raw_trace_documents if isinstance(document, str) and document.strip()]
            if isinstance(raw_trace_documents, list)
            else []
        )
        supplier_approved = inputs.get("supplier_approved")
        certificate_status = str(inputs.get("certificate_status") or "").strip().lower()
        expiration_date = inputs.get("expiration_date")
        requested_cert = inputs.get("requested_certificate_type")
        requested_condition = inputs.get("requested_condition")
        
        issues = []
        trace_issue = False
        requirement_issue = False
        sanctions_issue = False
        documentation_issue = False
        certificate_expired = False
        supplier_identity = supplier_name.strip().lower()
        supplier_blocked = (
            (source == "Supplier" and supplier_approved is False)
            or "sanction" in supplier_identity
            or "blacklist" in supplier_identity
        )
        if supplier_blocked:
            issues.append(f"Supplier '{supplier_name}' is not approved.")
            sanctions_issue = True
        elif source == "Supplier" and supplier_approved is not True:
            issues.append("Supplier approval has not been verified.")
            documentation_issue = True

        valid_certs = {"FAA 8130-3", "EASA Form 1", "CoC"}
        if cert_type not in valid_certs:
            issues.append(f"Missing valid airworthiness certificate (got '{cert_type}').")
            documentation_issue = True

        if certificate_status == "expired":
            issues.append("Certificate has expired.")
            certificate_expired = True
        elif certificate_status and certificate_status != "valid":
            issues.append("Certificate validity has not been verified.")
            documentation_issue = True

        if expiration_date:
            try:
                if datetime.date.fromisoformat(str(expiration_date)) < datetime.date.today():
                    if "Certificate has expired." not in issues:
                        issues.append("Certificate has expired.")
                    certificate_expired = True
            except ValueError:
                issues.append("Certificate expiration date is invalid.")
                documentation_issue = True

        if not has_trace or (source == "Supplier" and not trace_documents):
            issues.append("Incomplete traceability information.")
            trace_issue = True

        if requested_cert and cert_type != requested_cert and not any("Requested certificate mismatch" in issue for issue in issues):
            issues.append(f"Requested certificate mismatch: expected {requested_cert}, got {cert_type}.")
            requirement_issue = True
        if requested_condition and inputs.get("condition") and inputs.get("condition") != requested_condition:
            issues.append(f"Condition mismatch: expected {requested_condition}, got {inputs.get('condition')}.")
            requirement_issue = True
        
        # Determine final compliance status based on gathered issues
        if not issues:
            compliance_status = "APPROVED"
        elif sanctions_issue or certificate_expired:
            compliance_status = "REJECTED"
        elif trace_issue or requirement_issue or documentation_issue:
            compliance_status = "HUMAN_REVIEW_REQUIRED"
        else:
            compliance_status = "REJECTED"

        escalation = (
            self.metadata.escalation_rules[1]
            if trace_issue
            else self.metadata.escalation_rules[0]
            if compliance_status == "HUMAN_REVIEW_REQUIRED"
            else None
        )

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
