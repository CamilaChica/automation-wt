import os
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from models.db_models import RFQ, RFQItem, Quote, QuoteItem, AgentAuditLog, Supplier
from services.db_service import db_service
from services.orchestration_service import orchestration_service
from services.mailbox_service import fetch_inbox_headers, send_message, send_otp_email
from api.auth import current_user, init_auth_db, request_otp, require_roles, verify_otp

app = FastAPI(
    title="Winged Tycoons RFQ-to-Quote Multi-Agent API",
    description="Automated multi-agent processing pipeline with Human-in-the-Loop approval gates.",
    version="1.0.0"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("FRONTEND_ORIGIN", "http://localhost:3000").split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)

# API Schemas
class IntakeRequest(BaseModel):
    raw_text: str = Field(..., description="Raw email or RFQ text submitted by customer")
    customer_name: Optional[str] = Field(None, description="Customer company or contact name")
    customer_email: Optional[str] = Field(None, description="Customer email for quote updates")

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

# Endpoints

@app.post("/api/auth/otp/request")
async def otp_request(request: OtpRequest):
    challenge_id, code = request_otp(request.email, request.role, request.full_name)
    response = {"challenge_id": challenge_id, "message": "If eligible, an OTP has been sent."}
    if os.getenv("WT_AUTH_ENV", "development") == "production":
        send_otp_email(request.email, code)
    else:
        response["development_otp"] = code
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
        raw_text=request.raw_text
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
async def list_rfqs(_user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING"))):
    """
    Retrieves all RFQs.
    """
    return db_service.list_rfqs()

@app.get("/api/rfqs/{rfq_id}")
async def get_rfq_detail(rfq_id: str, user: dict = Depends(current_user)):
    """
    Retrieves complete status details, items, audit logs, and associated quotes.
    """
    rfq = db_service.get_rfq(rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found.")
    if user["role"] == "ROLE_CUSTOMER" and rfq.customer_email.lower() != user["email"].lower():
        raise HTTPException(status_code=403, detail="You can only access your own requests.")
        
    items = db_service.get_rfq_items(rfq_id)
    logs = db_service.get_audit_logs(rfq_id)
    quote = db_service.get_quote_by_rfq(rfq_id)
    
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
    return list(db_service.suppliers.values())

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
    return {"mailbox": mailbox, "messages": fetch_inbox_headers(mailbox)}

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
