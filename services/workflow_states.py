"""Canonical RFQ lifecycle states and guarded transitions."""

from enum import StrEnum


class WorkflowState(StrEnum):
    INTAKE_LEGACY = "Intake"
    VALIDATING_LEGACY = "Validating"
    INVENTORY_LOOKUP_LEGACY = "Inventory_Lookup"
    SUPPLIER_SOURCING_LEGACY = "Supplier_Sourcing"
    QUOTE_GENERATION_LEGACY = "Quote_Generation"
    PENDING_APPROVAL_LEGACY = "Pending_Approval"
    PENDING_APPROVAL_LOW_MARGIN_LEGACY = "Pending_Approval_Low_Margin"
    QUOTE_SENT_LEGACY = "Quote_Sent"
    QUOTE_DISPATCH_PENDING_LEGACY = "Quote_Dispatch_Pending"
    QUOTE_DISPATCH_FAILED_LEGACY = "Quote_Dispatch_Failed"
    PENDING_PO_REVIEW_LEGACY = "Pending_PO_Review"
    PURCHASE_ORDER_RECEIVED_LEGACY = "Purchase_Order_Received"
    INTAKE_FAILED = "Intake_Failed"
    INTERNAL_REVIEW_PENDING = "Pending_Internal_Review"
    COMPLIANCE_REVIEW_BLOCKED = "Blocked_Compliance_Review"
    VERIFICATION_HALTED = "Verification_Halted"
    SUPPLIER_SOURCING_FAILED = "Sourcing_Failed"
    SUPPLIER_CONFIRMATION_REQUESTED = "Supplier_Confirmation_Requested"
    NO_QUOTE = "No_Quote"
    COMPLIANCE_CHECK = "Compliance_Check"
    COMPLIANCE_BLOCKED = "Compliance_Blocked"
    COMPLIANCE_WARNING = "Compliance_Warning"
    PRICING = "Pricing"
    REJECTED = "Rejected"
    PO_VALIDATED_LEGACY = "PO_Validated"
    NEW_RFQ = "NEW_RFQ"
    RFQ_VALIDATED = "RFQ_VALIDATED"
    SEARCHING_INVENTORY = "SEARCHING_INVENTORY"
    SOURCING_SUPPLIERS = "SOURCING_SUPPLIERS"
    WAITING_SUPPLIER_RESPONSE = "WAITING_SUPPLIER_RESPONSE"
    SUPPLIER_QUOTE_RECEIVED = "SUPPLIER_QUOTE_RECEIVED"
    CUSTOMER_QUOTE_READY = "CUSTOMER_QUOTE_READY"
    QUOTE_SENT = "QUOTE_SENT"
    QUOTE_DISPATCH_PENDING = "QUOTE_DISPATCH_PENDING"
    FOLLOW_UP_PENDING = "FOLLOW_UP_PENDING"
    PO_RECEIVED = "PO_RECEIVED"
    PO_VALIDATED = "PO_VALIDATED"
    SUPPLIER_AVAILABILITY_PENDING = "SUPPLIER_AVAILABILITY_PENDING"
    SUPPLIER_CONFIRMED = "SUPPLIER_CONFIRMED"
    READY_FOR_FULFILLMENT = "READY_FOR_FULFILLMENT"


LEGACY_TO_CANONICAL = {
    "Intake": WorkflowState.NEW_RFQ,
    "Validating": WorkflowState.RFQ_VALIDATED,
    "Inventory_Lookup": WorkflowState.SEARCHING_INVENTORY,
    "Supplier_Sourcing": WorkflowState.SOURCING_SUPPLIERS,
    "Supplier_Confirmation_Requested": WorkflowState.SOURCING_SUPPLIERS,
    "Quote_Generation": WorkflowState.CUSTOMER_QUOTE_READY,
    "Pending_Approval": WorkflowState.CUSTOMER_QUOTE_READY,
    "Pending_Approval_Low_Margin": WorkflowState.CUSTOMER_QUOTE_READY,
    "Quote_Sent": WorkflowState.QUOTE_SENT,
    "Quote_Dispatch_Pending": WorkflowState.QUOTE_DISPATCH_PENDING,
    "Quote_Dispatch_Failed": WorkflowState.CUSTOMER_QUOTE_READY,
    "Pending_PO_Review": WorkflowState.PO_RECEIVED,
    "Purchase_Order_Received": WorkflowState.PO_RECEIVED,
}


LEGACY_TRANSITIONS = {
    "Intake": {"Validating", "Intake_Failed", "Supplier_Sourcing", "Pending_Internal_Review", "Blocked_Compliance_Review"},
    "Intake_Failed": {"Intake"},
    "Validating": {"Inventory_Lookup", "Supplier_Sourcing", "Verification_Halted"},
    "Inventory_Lookup": {"Supplier_Sourcing", "Compliance_Check", "Verification_Halted"},
    "Supplier_Sourcing": {"Sourcing_Failed", "Compliance_Check", "Supplier_Sourcing", "No_Quote", "Verification_Halted"},
    "Sourcing_Failed": {"No_Quote", "Supplier_Sourcing"},
    "No_Quote": {"Supplier_Sourcing"},
    "Compliance_Check": {"Compliance_Blocked", "Compliance_Warning", "Pricing"},
    "Pricing": {"Quote_Generation"},
    "Quote_Generation": {"Pending_Approval", "Quote_Sent", "Quote_Dispatch_Pending", "Quote_Dispatch_Failed", "Pending_Internal_Review"},
    "Quote_Dispatch_Pending": {"Quote_Sent", "Quote_Dispatch_Failed", "Pending_Internal_Review"},
    "Pending_Approval": {"Pending_Approval_Low_Margin", "Quote_Sent", "Quote_Dispatch_Pending", "Rejected", "Pending_Internal_Review"},
    "Pending_Approval_Low_Margin": {"Quote_Sent", "Quote_Dispatch_Pending", "Rejected", "Pending_Internal_Review"},
    "Quote_Sent": {"Pending_PO_Review", "Purchase_Order_Received", "Rejected"},
    "Pending_PO_Review": {"Purchase_Order_Received", "Rejected"},
    "Purchase_Order_Received": {"PO_Validated", "Rejected"},
    "PO_Validated": {"SUPPLIER_AVAILABILITY_PENDING", "Rejected"},
    "SUPPLIER_AVAILABILITY_PENDING": {"SUPPLIER_CONFIRMED", "Rejected"},
    "SUPPLIER_CONFIRMED": {"READY_FOR_FULFILLMENT"},
}


class InvalidWorkflowTransition(ValueError):
    """Raised when an RFQ attempts an unrecognized lifecycle transition."""


def canonical_state(status: str) -> str:
    if status not in {state.value for state in WorkflowState}:
        raise InvalidWorkflowTransition(f"Unknown RFQ workflow state '{status}'.")
    return LEGACY_TO_CANONICAL.get(status, status)


def validate_transition(current: str, requested: str) -> None:
    current_state = canonical_state(current)
    requested_state = canonical_state(requested)
    if current_state == requested_state:
        return
    allowed = set()
    for legacy_current, targets in LEGACY_TRANSITIONS.items():
        if canonical_state(legacy_current) == current_state:
            allowed.update(canonical_state(target) for target in targets)
    if requested_state not in allowed:
        raise InvalidWorkflowTransition(
            f"Invalid RFQ transition from '{current}' to '{requested}'."
        )
