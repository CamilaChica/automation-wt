"""Canonical RFQ lifecycle states and guarded transitions."""

from enum import StrEnum


class WorkflowState(StrEnum):
    NEW_RFQ = "NEW_RFQ"
    RFQ_VALIDATED = "RFQ_VALIDATED"
    SEARCHING_INVENTORY = "SEARCHING_INVENTORY"
    SOURCING_SUPPLIERS = "SOURCING_SUPPLIERS"
    WAITING_SUPPLIER_RESPONSE = "WAITING_SUPPLIER_RESPONSE"
    SUPPLIER_QUOTE_RECEIVED = "SUPPLIER_QUOTE_RECEIVED"
    CUSTOMER_QUOTE_READY = "CUSTOMER_QUOTE_READY"
    QUOTE_SENT = "QUOTE_SENT"
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
    "Quote_Generation": WorkflowState.CUSTOMER_QUOTE_READY,
    "Pending_Approval": WorkflowState.CUSTOMER_QUOTE_READY,
    "Pending_Approval_Low_Margin": WorkflowState.CUSTOMER_QUOTE_READY,
    "Quote_Sent": WorkflowState.QUOTE_SENT,
    "Pending_PO_Review": WorkflowState.PO_RECEIVED,
    "Purchase_Order_Received": WorkflowState.PO_RECEIVED,
}


LEGACY_TRANSITIONS = {
    "Intake": {"Validating", "Intake_Failed", "Supplier_Sourcing", "Blocked_Compliance_Review"},
    "Validating": {"Inventory_Lookup", "Supplier_Sourcing", "Verification_Halted"},
    "Inventory_Lookup": {"Supplier_Sourcing", "Compliance_Check"},
    "Supplier_Sourcing": {"Sourcing_Failed", "Compliance_Check", "Supplier_Sourcing"},
    "Compliance_Check": {"Compliance_Blocked", "Compliance_Warning", "Pricing"},
    "Pricing": {"Quote_Generation"},
    "Quote_Generation": {"Pending_Approval", "Quote_Sent"},
    "Pending_Approval": {"Pending_Approval_Low_Margin", "Quote_Sent", "Rejected"},
    "Pending_Approval_Low_Margin": {"Quote_Sent", "Rejected"},
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
    return LEGACY_TO_CANONICAL.get(status, status)


def validate_transition(current: str, requested: str) -> None:
    if current == requested:
        return
    allowed = LEGACY_TRANSITIONS.get(current)
    if allowed is None:
        return
    if requested not in allowed:
        raise InvalidWorkflowTransition(
            f"Invalid RFQ transition from '{current}' to '{requested}'."
        )
