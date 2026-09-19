import os
import secrets
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Request

load_dotenv()
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from models.db_models import RFQ, RFQItem, Quote, QuoteItem, AgentAuditLog, Supplier
from services.db_service import db_service
from services.orchestration_service import orchestration_service
from services.mailbox_service import fetch_inbox_messages, fetch_inbox_headers, send_message, send_otp_email
from services.communication_service import communication_service
from services.supplier_database import supplier_db
from services.carrier_tracking_service import carrier_tracking_service
from api.auth import current_user, init_auth_db, request_otp, require_roles, verify_otp

app = FastAPI(
    title="Winged Tycoons RFQ-to-Quote Multi-Agent API",
    description="Automated multi-agent processing pipeline with Human-in-the-Loop approval gates.",
    version="1.0.0"
)
allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGIN",
        "http://localhost:3000,https://winged-tycoons-frontend.onrender.com",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)

# API Schemas
class IntakeRequest(BaseModel):
    raw_text: str = Field(..., description="Raw email or RFQ text submitted by customer")
    customer_name: Optional[str] = Field(None, description="Customer company or contact name")
    customer_email: Optional[str] = Field(None, description="Customer email for quote updates")
    reply_to: Optional[str] = Field(None, description="Original email message ID for same-thread replies")

class OtpRequest(BaseModel):
    email: str
    role: str
    full_name: str = ""

class OtpVerifyRequest(BaseModel):
    challenge_id: str
    code: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    email: str

class CatalogItem(BaseModel):
    part_number: str
    condition_code: str
    quantity_available: int
    certificate_type: str
    has_full_trace: bool

class CustomerQuoteItem(BaseModel):
    part_number: str
    quantity: int
    unit_price: float
    certificate_type: str
    compliance_status: str

class CustomerQuote(BaseModel):
    id: str
    rfq_id: str
    subtotal: float
    shipping_cost: float
    total_amount: float
    status: str

class CustomerQuoteDetails(BaseModel):
    quote: CustomerQuote
    items: List[CustomerQuoteItem]

class CustomerRFQDetail(BaseModel):
    rfq: RFQ
    items: List[RFQItem]
    quote_details: Optional[CustomerQuoteDetails] = None

class IntakeResponse(BaseModel):
    rfq_id: str
    status: str
    message: str

class OverrideItem(BaseModel):
    quote_item_id: str
    unit_price: float

class ApproveRequest(BaseModel):
    operator_name: str = Field("John Doe", description="Authorized agent name approving the quote")
    comments: Optional[str] = None
    items_override: Optional[List[OverrideItem]] = None

class RejectRequest(BaseModel):
    operator_name: str
    comments: str

class MailboxMessageRequest(BaseModel):
    recipient: str
    subject: str
    body: str
    reply_to: Optional[str] = None

class PurchaseOrderRequest(BaseModel):
    quote_id: str
    po_number: str
    customer_email: Optional[str] = None

class ShipmentCreateRequest(BaseModel):
    rfq_id: str
    quote_id: Optional[str] = None
    part_numbers: List[str]
    quantity: int = Field(..., ge=1)

class ShipmentEventRequest(BaseModel):
    status: str
    location: Optional[str] = None
    description: str

class CarrierTrackingRequest(BaseModel):
    carrier: str
    tracking_number: str

# Endpoints

@app.post("/api/auth/otp/request")
async def otp_request(request: OtpRequest):
    challenge_id, code = request_otp(request.email, request.role, request.full_name)
    response = {"challenge_id": challenge_id, "message": "If eligible, an OTP has been sent."}
    auth_env = os.getenv("WT_AUTH_ENV", "development").strip().lower()
    if auth_env == "production":
        send_otp_email(request.email, code)
    elif auth_env == "development":
        response["development_otp"] = code
    else:
        raise HTTPException(status_code=500, detail="WT_AUTH_ENV must be 'development' or 'production'.")
    return response

@app.post("/api/auth/otp/verify", response_model=LoginResponse)
async def otp_verify(request: OtpVerifyRequest):
    result = verify_otp(request.challenge_id, request.code)
    return LoginResponse(
        access_token=result["access_token"],
        role=result["role"],
        email=result["email"],
    )

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "Winged Tycoons RFQ-to-Quote Multi-Agent API",
        "version": "1.0.0",
        "docs_url": "/docs",
        "frontend_url": "http://localhost:3000"
    }

@app.post("/api/rfqs/intake", response_model=IntakeResponse)
async def submit_rfq(request: IntakeRequest, user: dict = Depends(current_user)):
    """
    Submits raw unstructured text representing a customer RFQ.
    Triggers parsing and initial pipeline validation.
    """
    if not request.raw_text.strip():
        raise HTTPException(status_code=400, detail="Raw RFQ text cannot be empty.")
        
    # Standard mock customer resolution (simulating a database record lookup)
    if user["role"] == "customer":
        customer_name = request.customer_name or user["email"]
        customer_email = user["email"]
    else:
        customer_name = request.customer_name or "Delta MRO Services"
        customer_email = request.customer_email or "procurement@deltamro.com"
    if not request.customer_name and "united" in request.raw_text.lower():
        customer_name = "United Aerospace"
        customer_email = "parts@unitedaero.com"
        
    # Write to DB
    rfq = db_service.create_rfq(
        customer_name=customer_name,
        customer_email=customer_email,
        raw_text=request.raw_text,
        thread_id=request.reply_to,
    )
    
    db_service.add_audit_log(
        rfq.id, "GatewayAPI", "intake_submission",
        f"RFQ submitted successfully for customer '{customer_name}'."
    )
    
    # Run the pipeline synchronously to make parsing results immediately available in MVP
    pipeline_res = await orchestration_service.process_rfq_pipeline(rfq.id)
    
    status = pipeline_res.get("status", rfq.status)
    error = pipeline_res.get("error", "")
    
    msg = "RFQ received and processed successfully."
    if "Failed" in status or "Halted" in status or "Warning" in status:
        msg = f"RFQ pipeline halted or failed: {error}"
        
    return IntakeResponse(
        rfq_id=rfq.id,
        status=status,
        message=msg
    )

@app.post("/api/rfqs/{rfq_id}/process")
async def trigger_process(rfq_id: str, _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING"))):
    """
    Manually advances the state-machine of the RFQ pipeline.
    """
    rfq = db_service.get_rfq(rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found.")
        
    res = await orchestration_service.process_rfq_pipeline(rfq_id)
    return res

@app.get("/api/rfqs", response_model=List[RFQ])
async def list_rfqs(user: dict = Depends(current_user)):
    """
    Retrieves all RFQs.
    """
    rfqs = db_service.list_rfqs()
    if user["role"] == "ROLE_CUSTOMER":
        return [rfq for rfq in rfqs if rfq.customer_email.lower() == user["email"].lower()]
    if user["role"] not in ("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING"):
        raise HTTPException(status_code=403, detail="Insufficient permissions.")
    return rfqs

@app.get("/api/rfqs/{rfq_id}")
async def get_rfq_detail(rfq_id: str, user: dict = Depends(current_user)) -> CustomerRFQDetail | dict:
    """
    Retrieves complete status details, items, audit logs, and associated quotes.
    """
    rfq = db_service.get_rfq(rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found.")
    if user["role"] == "ROLE_CUSTOMER" and rfq.customer_email.lower() != user["email"].lower():
        raise HTTPException(status_code=403, detail="You can only access your own requests.")
        
    items = db_service.get_rfq_items(rfq_id)
    quote = db_service.get_quote_by_rfq(rfq_id)

    if user["role"] == "ROLE_CUSTOMER":
        quote_details = None
        if quote:
            quote_details = CustomerQuoteDetails(
                quote=CustomerQuote(
                    id=quote.id,
                    rfq_id=quote.rfq_id,
                    subtotal=quote.subtotal,
                    shipping_cost=quote.shipping_cost,
                    total_amount=quote.total_amount,
                    status=quote.status,
                ),
                items=[
                    CustomerQuoteItem(
                        part_number=item.part_number,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        certificate_type=item.certificate_type,
                        compliance_status=item.compliance_status,
                    )
                    for item in db_service.get_quote_items(quote.id)
                ],
            )
        return CustomerRFQDetail(rfq=rfq, items=items, quote_details=quote_details)

    if user["role"] not in ("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING"):
        raise HTTPException(status_code=403, detail="Insufficient permissions.")

    logs = db_service.get_audit_logs(rfq_id)
    
    quote_details = None
    if quote:
        quote_items = db_service.get_quote_items(quote.id)
        quote_details = {
            "quote": quote,
            "items": quote_items
        }
        
    return {
        "rfq": rfq,
        "items": items,
        "logs": logs,
        "quote_details": quote_details
    }

@app.post("/api/quotes/{quote_id}/approve")
async def approve_quote(quote_id: str, request: ApproveRequest, _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES"))):
    """
    Performs Human-in-the-Loop quote approval and sends final offer.
    Supports pricing overrides.
    """
    quote = db_service.get_quote(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found.")
        
    overrides_list = []
    if request.items_override:
        overrides_list = [{"quote_item_id": o.quote_item_id, "unit_price": o.unit_price} for o in request.items_override]
        
    res = await orchestration_service.approve_and_send_quote(
        quote_id=quote_id,
        operator_name=request.operator_name,
        overrides=overrides_list
    )
    
    # Update comments in database
    db_service.update_quote_status(quote_id, quote.status, comments=request.comments)
    
    return res

@app.post("/api/quotes/{quote_id}/reject")
async def reject_quote(quote_id: str, request: RejectRequest, _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES"))):
    """
    Rejects proposal and shifts state.
    """
    quote = db_service.get_quote(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found.")
        
    db_service.update_quote_status(
        quote_id, "Rejected", 
        approved_by=request.operator_name, 
        comments=request.comments
    )
    db_service.update_rfq_status(quote.rfq_id, "Rejected")
    
    db_service.add_audit_log(
        quote.rfq_id, "Orchestrator", "human_rejection",
        f"Quote rejected by {request.operator_name}. Reason: {request.comments}",
        "WARNING"
    )
    
    return {"status": "Rejected", "quote_id": quote_id}

@app.post("/api/purchase-orders")
async def submit_purchase_order(request: PurchaseOrderRequest, user: dict = Depends(current_user)):
    """Receive a customer PO and route its purchasing details to the human team."""
    quote = db_service.get_quote(request.quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found.")
    rfq = db_service.get_rfq(quote.rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found.")

    customer_email = request.customer_email or rfq.customer_email
    if user["role"] == "ROLE_CUSTOMER" and customer_email.lower() != user["email"].lower():
        raise HTTPException(status_code=403, detail="You can only submit a purchase order for your own quote.")

    quote_items = db_service.get_quote_items(request.quote_id)
    internal_items = []
    supplier_groups: Dict[str, Dict[str, Any]] = {}
    for item in quote_items:
        offers = supplier_db.find_supplier_offers(item.part_number, quantity_needed=item.quantity)
        selected = next(
            (offer for offer in offers if abs(float(offer.get("unit_cost") or 0) - float(item.unit_cost or 0)) < 0.01),
            offers[0] if offers else None,
        )
        supplier_name = selected.get("supplier_name") if selected else "Internal inventory"
        supplier_email = selected.get("supplier_email") if selected else ""
        internal_item = {
            "part_number": item.part_number,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "supplier_name": supplier_name,
            "supplier_email": supplier_email,
            "supplier_unit_cost": float(selected.get("unit_cost") or item.unit_cost or 0) if selected else float(item.unit_cost or 0),
        }
        internal_items.append(internal_item)
        if supplier_email:
            supplier_groups.setdefault(supplier_email, {"supplier_name": supplier_name, "items": []})["items"].append(internal_item)

    notification = communication_service.notify_purchase_order(
        recipient=os.getenv("PURCHASE_ORDER_NOTIFICATION_EMAIL", "camila@wingedtycoons.com"),
        po_number=request.po_number,
        customer_name=rfq.customer_name,
        customer_email=customer_email,
        quote_id=request.quote_id,
        items=internal_items,
    )
    confirmations = [
        communication_service.request_supplier_availability_confirmation(
            recipient=supplier_email,
            supplier_name=group["supplier_name"],
            po_number=request.po_number,
            items=group["items"],
            reply_to=None,
        )
        for supplier_email, group in supplier_groups.items()
    ]
    db_service.update_rfq_status(rfq.id, "Purchase_Order_Received")
    db_service.add_audit_log(
        rfq.id,
        "PurchaseOrderAgent",
        "purchase_order_received",
        f"Purchase order {request.po_number} received and routed for human purchasing review.",
        "SUCCESS",
    )
    return {
        "status": "Purchase_Order_Received",
        "po_number": request.po_number,
        "quote_id": request.quote_id,
        "internal_notification": notification,
        "supplier_confirmation_count": len(confirmations),
    }

@app.get("/api/shipments/track/{public_token}")
async def track_shipment(public_token: str):
    """Return customer-safe shipment status using an opaque tracking token."""
    shipment = db_service.get_shipment_by_token(public_token)
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found.")
    return {
        "shipment_id": shipment.id,
        "status": shipment.status,
        "part_numbers": shipment.part_numbers,
        "quantity": shipment.quantity,
        "carrier": shipment.carrier,
        "tracking_number": shipment.tracking_number,
        "estimated_delivery": shipment.estimated_delivery,
        "events": [event.model_dump(mode="json") for event in db_service.get_shipment_events(shipment.id)],
    }

@app.post("/api/internal/shipments")
async def create_shipment(
    request: ShipmentCreateRequest,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING")),
):
    rfq = db_service.get_rfq(request.rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found.")
    shipment = db_service.create_shipment(
        rfq_id=request.rfq_id,
        quote_id=request.quote_id,
        customer_email=rfq.customer_email,
        part_numbers=request.part_numbers,
        quantity=request.quantity,
        public_token=secrets.token_urlsafe(24),
    )
    tracking_notification = communication_service.send_shipment_tracking_link(
        recipient=rfq.customer_email,
        shipment_id=shipment.id,
        public_token=shipment.public_token,
    )
    return {
        "shipment_id": shipment.id,
        "tracking_url": f"/track/{shipment.public_token}",
        "status": shipment.status,
        "tracking_notification": tracking_notification["transmission_status"],
    }

@app.get("/api/internal/shipments")
async def list_shipments(
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING")),
):
    return db_service.list_shipments()

@app.post("/api/internal/shipments/{shipment_id}/events")
async def add_shipment_event(
    shipment_id: str,
    request: ShipmentEventRequest,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING")),
):
    if not db_service.get_shipment(shipment_id):
        raise HTTPException(status_code=404, detail="Shipment not found.")
    event = db_service.add_shipment_event(shipment_id, request.status, request.location, request.description)
    return {"status": "updated", "event": event}

@app.post("/api/internal/shipments/{shipment_id}/tracking")
async def register_carrier_tracking(
    shipment_id: str,
    request: CarrierTrackingRequest,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING")),
):
    shipment = db_service.update_shipment_tracking(shipment_id, request.carrier, request.tracking_number)
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found.")
    provider_result = carrier_tracking_service.create_tracker(
        request.carrier,
        request.tracking_number,
        title=f"Winged Tycoons shipment {shipment_id}",
    )
    return {
        "shipment_id": shipment_id,
        "carrier": request.carrier,
        "tracking_number": request.tracking_number,
        "provider": provider_result,
    }

@app.post("/api/internal/shipments/{shipment_id}/tracking/refresh")
async def refresh_carrier_tracking(
    shipment_id: str,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING")),
):
    shipment = db_service.get_shipment(shipment_id)
    if not shipment or not shipment.carrier or not shipment.tracking_number:
        raise HTTPException(status_code=404, detail="Shipment tracking is not registered.")
    payload = carrier_tracking_service.get_tracker(shipment.carrier, shipment.tracking_number)
    normalized = carrier_tracking_service.normalize_webhook(payload)
    event = db_service.add_shipment_event(
        shipment_id,
        normalized["status"],
        normalized.get("location"),
        normalized["description"],
    )
    return {"shipment_id": shipment_id, "event": event, "provider": payload}

@app.post("/api/webhooks/carriers/aftership")
async def carrier_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("aftership-hmac-sha256") or request.headers.get("x-aftership-signature") or request.headers.get("x-webhook-signature")
    if not carrier_tracking_service.verify_webhook(body, signature):
        raise HTTPException(status_code=401, detail="Invalid carrier webhook signature.")
    payload = await request.json()
    normalized = carrier_tracking_service.normalize_webhook(payload)
    shipment = db_service.find_shipment_by_tracking(
        normalized.get("carrier", ""), normalized.get("tracking_number", "")
    )
    if not shipment:
        raise HTTPException(status_code=404, detail="No shipment matches carrier tracking event.")
    event = db_service.add_shipment_event(
        shipment.id,
        normalized["status"],
        normalized.get("location"),
        normalized["description"],
    )
    return {"status": "accepted", "shipment_id": shipment.id, "event_id": event.id}

@app.get("/api/catalog/search", response_model=List[CatalogItem])
async def search_catalog(query: str = "", _user: dict = Depends(require_roles("ROLE_CUSTOMER", "ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING"))):
    """Public, customer-safe catalog availability search.

    Deliberately omits internal costs, serial numbers, and warehouse locations.
    """
    normalized_query = query.strip().lower()
    results = []
    for item in db_service.inventory.values():
        if normalized_query and normalized_query not in item.part_number.lower():
            continue
        results.append(CatalogItem(
            part_number=item.part_number,
            condition_code=item.condition_code,
            quantity_available=item.quantity_available,
            certificate_type=item.certificate_type,
            has_full_trace=item.has_full_trace,
        ))
    return results

@app.get("/api/inventory")
async def get_inventory(_user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING"))):
    """
    Fetch mock internal stock inventory.
    """
    return list(db_service.inventory.values())

@app.get("/api/suppliers", response_model=List[Supplier])
async def list_suppliers(_user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING"))):
    """
    Returns the full supplier directory with contact information.
    """
    rows = supplier_db.list_suppliers()
    return [
        Supplier(
            id=row["id"],
            company_name=row["company_name"],
            contact_name=row["company_name"],
            phone=row["phone"] or "",
            email=row["email"] or "",
            approval_status=row["approval_status"],
            itar_certified=bool(row.get("itar_certified", 0)),
            account_manager=None,
        )
        for row in rows
    ]

@app.get("/api/supplier-offers")
async def list_supplier_offers(
    part_number: str = "",
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING", "ROLE_SALES")),
):
    if not part_number.strip():
        return []
    return supplier_db.find_supplier_offers(part_number.strip().upper(), quantity_needed=1)

@app.get("/api/suppliers/{supplier_id}", response_model=Supplier)
async def get_supplier(supplier_id: str, _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING"))):
    """
    Returns a single supplier's full contact and compliance profile.
    """
    supplier = db_service.suppliers.get(supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail=f"Supplier '{supplier_id}' not found.")
    return supplier

@app.get("/api/internal/mailboxes/{mailbox}/inbox")
async def mailbox_inbox(mailbox: str, user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING"))):
    if mailbox not in ("sales", "purchasing"):
        raise HTTPException(404, "Mailbox not found.")
    if mailbox == "sales" and user["role"] not in ("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES"):
        raise HTTPException(403, "You do not have access to the sales mailbox.")
    if mailbox == "purchasing" and user["role"] not in ("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING"):
        raise HTTPException(403, "You do not have access to the purchasing mailbox.")
    return {"mailbox": mailbox, "messages": fetch_inbox_messages(mailbox)}

@app.post("/api/internal/mailboxes/{mailbox}/send")
async def mailbox_send(
    mailbox: str,
    request: MailboxMessageRequest,
    user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING")),
):
    if mailbox not in ("sales", "purchasing"):
        raise HTTPException(404, "Mailbox not found.")
    allowed = mailbox == "sales" and user["role"] in ("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES")
    allowed = allowed or mailbox == "purchasing" and user["role"] in ("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING")
    if not allowed:
        raise HTTPException(403, "You do not have send access to this mailbox.")
    send_message(mailbox, request.recipient, request.subject, request.body, request.reply_to)
    return {"status": "sent", "mailbox": mailbox, "sent_by": user["email"]}
