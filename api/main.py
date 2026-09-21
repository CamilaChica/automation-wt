import os
import secrets
import uuid
import json
import logging
import time
from pathlib import Path
from collections import defaultdict, deque
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Request, Response
from fastapi.responses import FileResponse

load_dotenv()
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from models.db_models import RFQ, RFQItem, Quote, QuoteItem, AgentAuditLog, Supplier
from services.db_service import db_service
from services.orchestration_service import orchestration_service
from services.mailbox_service import fetch_inbox_messages, fetch_inbox_headers, health_check_mailboxes, send_message, send_otp_email
from services.communication_service import communication_service
from services.supplier_database import supplier_db
from services.carrier_tracking_service import carrier_tracking_service
from services.twilio_service import twilio_service
from services.freight_service import FreightRequest, freight_rate_service
from services.operations_store import operations_store
from services.export_control_service import export_control_service
from services.attachment_service import AttachmentService
from services.swarm_runtime import swarm_runtime
from api.auth import current_user, init_auth_db, request_otp, require_roles, verify_otp, ROLE_CUSTOMER

app = FastAPI(
    title="Winged Tycoons RFQ-to-Quote Multi-Agent API",
    description="Automated multi-agent processing pipeline with Human-in-the-Loop approval gates.",
    version="1.0.0"
)

attachment_service = AttachmentService()


class _JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        })


if not logging.getLogger().handlers:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
for _handler in logging.getLogger().handlers:
    _handler.setFormatter(_JsonLogFormatter())
logger = logging.getLogger("winged-tycoons.api")

_CSRF_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_CSRF_EXEMPT_PATHS = {"/healthz", "/ready", "/", "/api/auth/otp/request", "/api/auth/otp/verify"}
_RATE_LIMIT_RULES = {
    "/api/auth/otp/request": (3, 3600),
    "/api/auth/otp/verify": (10, 900),
    "/api/rfqs/intake": (30, 60),
    "/api/purchase-orders": (20, 60),
    "/api/catalog/search": (120, 60),
}
_rate_limit_events: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def _rate_limit(request: Request) -> tuple[bool, int]:
    rule = _RATE_LIMIT_RULES.get(request.url.path)
    if not rule or os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
        return True, 0
    limit, window = rule
    now = time.time()
    key = (request.url.path, _client_key(request))
    events = _rate_limit_events[key]
    while events and events[0] <= now - window:
        events.popleft()
    if len(events) >= limit:
        retry_after = max(1, int(events[0] + window - now))
        return False, retry_after
    events.append(now)
    return True, 0


@app.middleware("http")
async def security_headers(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    started = time.perf_counter()
    allowed, retry_after = _rate_limit(request)
    if not allowed:
        response = Response("Rate limit exceeded.", status_code=429)
        response.headers["Retry-After"] = str(retry_after)
        response.headers["X-Request-ID"] = request_id
        return response
    session_cookie = request.cookies.get("wt_session")
    csrf_cookie = request.cookies.get("wt_csrf")
    csrf_header = request.headers.get("x-csrf-token")
    if (
        request.method not in _CSRF_SAFE_METHODS
        and request.url.path not in _CSRF_EXEMPT_PATHS
        and session_cookie
        and not request.headers.get("authorization")
        and (not csrf_cookie or not csrf_header or not secrets.compare_digest(csrf_cookie, csrf_header))
    ):
        return Response("CSRF validation failed.", status_code=403, headers={"X-Request-ID": request_id})
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = str(duration_ms)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    csrf_token = csrf_cookie or secrets.token_urlsafe(24)
    response.set_cookie(
        "wt_csrf",
        csrf_token,
        httponly=False,
        secure=os.getenv("WT_AUTH_ENV", "development").strip().lower() == "production",
        samesite="Strict",
        max_age=8 * 60 * 60,
    )
    if os.getenv("WT_AUTH_ENV", "development").strip().lower() == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    logger.info(
        "http_request",
        extra={"request_id": request_id, "method": request.method, "path": request.url.path, "status_code": response.status_code, "duration_ms": duration_ms},
    )
    return response
configured_origins = {
    origin.strip()
    for origin in os.getenv("FRONTEND_ORIGIN", "").split(",")
    if origin.strip()
}
allowed_origins = sorted(configured_origins | {
    "http://localhost:3000",
    "http://localhost:5173",
    "https://winged-tycoons-frontend.onrender.com",
    "https://wingedtycoons.com",
    "https://rfq.wingedtycoons.com",
})
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Accept",
        "Authorization",
        "Content-Type",
        "X-CSRF-Token",
        "X-Internal-Role",
    ],
)

# API Schemas
class IntakeRequest(BaseModel):
    raw_text: str = Field(..., description="Raw email or RFQ text submitted by customer")
    customer_name: Optional[str] = Field(None, description="Customer company or contact name")
    customer_email: Optional[str] = Field(None, description="Customer email for quote updates")
    reply_to: Optional[str] = Field(None, description="Original email message ID for same-thread replies")
    customer_country: Optional[str] = Field(None, description="Customer or destination country for export screening")

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

class PurchaseOrderApprovalRequest(BaseModel):
    operator_name: str = Field(..., min_length=1)
    comments: Optional[str] = None

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

class ShipmentSmsRequest(BaseModel):
    recipient: str = Field(..., description="E.164 phone number")
    status: str
    tracking_url: Optional[str] = None

class AutomationPauseRequest(BaseModel):
    paused: bool
    reason: Optional[str] = None

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
async def otp_verify(request: OtpVerifyRequest, response: Response):
    result = verify_otp(request.challenge_id, request.code)
    auth_env = os.getenv("WT_AUTH_ENV", "development").strip().lower()
    response.set_cookie(
        key="wt_session",
        value=result["access_token"],
        httponly=True,
        secure=auth_env == "production",
        samesite="Strict",
        max_age=8 * 60 * 60,
    )
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


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    try:
        db_service.list_rfqs()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database not ready: {exc}") from exc
    return {"status": "ready"}


@app.get("/api/attachments/{attachment_id}")
async def download_attachment(attachment_id: str, user: dict = Depends(current_user)):
    """Download an accepted attachment without exposing arbitrary filesystem paths."""
    if user["role"] not in {"ROLE_CUSTOMER", "ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions.")

    normalized_id = attachment_id.strip().upper()
    if not normalized_id.startswith("ATT-") or len(normalized_id) != 20:
        raise HTTPException(status_code=404, detail="Attachment not found.")

    matches = list(attachment_service.storage_dir.glob(f"{normalized_id}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Attachment not found.")

    attachment_path = matches[0].resolve()
    storage_root = attachment_service.storage_dir.resolve()
    if storage_root not in attachment_path.parents:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    return FileResponse(attachment_path, filename=attachment_path.name)

@app.post("/api/rfqs/intake", response_model=IntakeResponse)
async def submit_rfq(request: IntakeRequest, user: dict = Depends(current_user)):
    """
    Submits raw unstructured text representing a customer RFQ.
    Triggers parsing and initial pipeline validation.
    """
    if not request.raw_text.strip():
        raise HTTPException(status_code=400, detail="Raw RFQ text cannot be empty.")
        
    # Standard mock customer resolution (simulating a database record lookup)
    if user["role"] == ROLE_CUSTOMER:
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

    if os.getenv("SWARM_SHADOW_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            await swarm_runtime.publish_rfq_received(
                rfq_id=rfq.id,
                raw_text=request.raw_text,
                customer_id=f"CUS-{customer_email.lower()}",
                customer_name=customer_name,
                customer_email=customer_email,
                thread_id=request.reply_to,
            )
            db_service.add_audit_log(
                rfq.id,
                "SwarmRuntime",
                "event_published",
                "Published event.rfq.received in shadow mode; sequential pipeline remains authoritative.",
            )
        except Exception as exc:
            db_service.add_audit_log(
                rfq.id,
                "SwarmRuntime",
                "event_publish_failed",
                f"Shadow event publication failed: {type(exc).__name__}: {exc}",
                "WARNING",
            )

    screening = export_control_service.screen(
        customer_name=customer_name,
        raw_text=request.raw_text,
        destination=request.customer_country,
    )
    if screening.blocked:
        db_service.update_rfq_status(rfq.id, "Blocked_Compliance_Review")
        db_service.add_audit_log(
            rfq.id,
            "ExportControlService",
            "export_screening",
            "RFQ blocked pending export-control compliance review.",
            "FAILURE",
            json.dumps(screening.model_dump()),
        )
        return IntakeResponse(
            rfq_id=rfq.id,
            status="Blocked_Compliance_Review",
            message="RFQ blocked pending export-control compliance review.",
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

@app.post("/api/internal/rfqs/{rfq_id}/automation")
async def set_automation_pause(
    rfq_id: str,
    request: AutomationPauseRequest,
    user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER")),
):
    rfq = db_service.set_rfq_automation_paused(rfq_id, request.paused, request.reason)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found.")
    db_service.add_audit_log(
        rfq_id,
        "AutomationControl",
        "automation_pause" if request.paused else "automation_resume",
        f"Automation {'paused' if request.paused else 'resumed'} by {user['email']}."
        + (f" Reason: {rfq.pause_reason}" if rfq.pause_reason else ""),
        "WARNING" if request.paused else "SUCCESS",
    )
    return {
        "rfq_id": rfq_id,
        "automation_paused": rfq.automation_paused,
        "pause_reason": rfq.pause_reason,
    }

@app.get("/api/internal/automation-events")
async def list_automation_events(
    status: Optional[str] = None,
    limit: int = 100,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING")),
):
    return operations_store.list_automation_events(status=status, limit=limit)


@app.get("/api/internal/llm/health")
async def llm_health(
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER")),
):
    """Report LLM routing and secret presence without exposing credentials."""
    return {
        "default_provider": os.getenv("LLM_DEFAULT_PROVIDER", "openai"),
        "customer_communication_provider": os.getenv("LLM_TASK_PROVIDERS", ""),
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "anthropic_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
        "fallback_enabled": os.getenv("LLM_ALLOW_TEMPLATE_FALLBACK", "true").strip().lower() in {"1", "true", "yes", "on"},
    }

@app.get("/api/internal/mailboxes/health")
async def mailbox_health(
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING")),
):
    """Return operational health for the shared sales and purchasing mailboxes."""
    return health_check_mailboxes()

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
    
    # Use the status produced by orchestration; the original object is stale after approval.
    final_status = res.get("status")
    if not final_status or res.get("error"):
        raise HTTPException(status_code=409, detail=res.get("error", "Quote approval failed."))
    db_service.update_quote_status(quote_id, final_status, comments=request.comments)
    
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
    if rfq.status in {"Purchase_Order_Received", "Pending_PO_Review"}:
        raise HTTPException(status_code=409, detail="Purchase order already received for this RFQ.")

    customer_email = request.customer_email or rfq.customer_email
    if user["role"] == "ROLE_CUSTOMER" and customer_email.lower() != user["email"].lower():
        raise HTTPException(status_code=403, detail="You can only submit a purchase order for your own quote.")

    previous_po_number = None
    previous_quote_id = None
    if rfq.status and rfq.status != "Intake":
        previous_po_number = rfq.status.replace("Purchase_Order_Received", "").strip() or None
    communication_service.validate_purchase_order_metadata(
        po_number=request.po_number,
        customer_email=customer_email,
        quote_id=request.quote_id,
        previous_po_number=previous_po_number,
        previous_quote_id=previous_quote_id,
    )

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
        review_url=os.getenv("SALES_DASHBOARD_URL") or os.getenv("PUBLIC_APP_URL", "http://localhost:3000"),
    )
    db_service.update_rfq_status(rfq.id, "Pending_PO_Review")
    db_service.add_audit_log(
        rfq.id,
        "PurchaseOrderAgent",
        "purchase_order_received",
        f"Purchase order {request.po_number} received; fulfillment and invoicing are blocked pending human review.",
        "SUCCESS",
    )
    return {
        "status": "Pending_PO_Review",
        "po_number": request.po_number,
        "quote_id": request.quote_id,
        "internal_notification": notification,
        "supplier_confirmation_count": 0,
    }

@app.post("/api/purchase-orders/{quote_id}/approve")
async def approve_purchase_order(
    quote_id: str,
    request: PurchaseOrderApprovalRequest,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING")),
):
    """Release a previously held PO for downstream purchasing work."""
    quote = db_service.get_quote(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found.")
    rfq = db_service.get_rfq(quote.rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found.")
    if rfq.status != "Pending_PO_Review":
        raise HTTPException(status_code=409, detail="PO is not waiting for human review.")

    db_service.update_rfq_status(rfq.id, "Purchase_Order_Received")
    db_service.add_audit_log(
        rfq.id,
        "PurchaseOrderAgent",
        "purchase_order_approved",
        f"PO approved by {request.operator_name}; downstream purchasing may proceed."
        + (f" Comments: {request.comments}" if request.comments else ""),
        "SUCCESS",
    )
    return {"status": "Purchase_Order_Received", "quote_id": quote_id, "rfq_id": rfq.id}

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
    if rfq.status == "Pending_PO_Review":
        raise HTTPException(status_code=409, detail="Fulfillment is blocked until the purchase order is approved by a human operator.")
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

@app.post("/api/internal/shipments/{shipment_id}/sms")
async def send_shipment_sms(
    shipment_id: str,
    request: ShipmentSmsRequest,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING", "ROLE_SALES")),
):
    if not db_service.get_shipment(shipment_id):
        raise HTTPException(status_code=404, detail="Shipment not found.")
    return twilio_service.send_shipment_update(
        recipient=request.recipient,
        shipment_id=shipment_id,
        status=request.status,
        tracking_url=request.tracking_url,
    )

@app.post("/api/internal/freight/quote")
async def quote_freight(
    request: FreightRequest,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING", "ROLE_SALES")),
):
    return freight_rate_service.quote(
        origin=request.origin,
        destination=request.destination,
        weight_kg=request.weight_kg,
        packages=request.packages,
        service_level=request.service_level,
    )

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
    if not operations_store.claim_carrier_webhook_event(normalized["event_id"]):
        return {"status": "duplicate", "shipment_id": shipment.id}
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
