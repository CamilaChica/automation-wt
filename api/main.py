import os
import hashlib
import secrets
import uuid
import json
import logging
import time
import re
import asyncio
from contextlib import nullcontext
from pathlib import Path
from collections import defaultdict, deque
from typing import List, Dict, Any, Optional, Literal
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, File, Request, Response, UploadFile
from fastapi.responses import FileResponse

_process_database_url = os.getenv("DATABASE_URL")
load_dotenv()
if _process_database_url is None:
    os.environ.pop("DATABASE_URL", None)
from services.database_safety import validate_development_database_target

validate_development_database_target(
    os.getenv("DATABASE_URL", ""), os.getenv("WT_ENV", os.getenv("WT_AUTH_ENV", "development"))
)
from config.env_check import validate_production_environment

validate_production_environment()
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from models.db_models import RFQ, RFQItem, Quote, QuoteItem, AgentAuditLog, InventoryItem, Supplier
from models.operational_models import AuditLogRecord
from services.db_service import db_service
from services.orchestration_service import (
    ReviewDecisionConflict,
    ReviewDecisionValidationError,
    orchestration_service,
)
from services.mailbox_service import fetch_inbox_messages, fetch_inbox_headers, health_check_mailboxes, send_message, send_otp_email
from services.communication_service import communication_service
from services.supplier_database import supplier_db
from services.carrier_tracking_service import carrier_tracking_service
from services.twilio_service import twilio_service
from services.freight_service import FreightRequest, freight_rate_service
from services.operations_store import operations_store
from services.persistence_status import persistence_status
from services.async_database import check_migration_state, create_engine_from_environment, get_async_db, preflight_database, search_supplier_inventory, session_scope
from repositories.runtime import create_operational_repositories
from repositories.rfq_repository import RFQRepository
from services.export_control_service import export_control_service
from services.attachment_service import AttachmentService
from services.swarm_runtime import swarm_runtime
from services.voice_service import (
    check_inventory_availability,
    get_customer_order_status,
    get_order_status,
    get_voice_dashboard,
    log_customer_concern,
)
from services.voice_media import initialize_voice_media
from api.auth import (
    AUTH_STORAGE_BACKEND,
    MAX_OTP_REQUESTS_PER_HOUR,
    current_user,
    init_auth_db,
    request_otp,
    require_roles,
    revoke_session,
    verify_otp,
    ROLE_CUSTOMER,
)
from services.shared_rate_limit import SharedRateLimitUnavailable, check_shared_rate_limit
from services.employee_profile_service import (
    employee_session,
    get_profile,
    record_clock_event,
    set_presence,
    update_profile,
    work_hours_report,
)

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
    "/api/auth/otp/request": (20, 3600),
    "/api/auth/otp/verify": (20, 900),
    "/api/rfqs/intake": (30, 60),
    "/api/purchase-orders": (20, 60),
    "/api/catalog/search": (120, 60),
    "/api/session": (8, 60),
    "/api/voice/tools/check_inventory_availability": (60, 60),
    "/api/voice/tools/get_order_status": (30, 60),
    "/api/voice/tools/log_customer_concern": (10, 60),
}
_rate_limit_events: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def _client_key(request: Request) -> str:
    # Render's proxy terminates TLS; the real client IP is the first X-Forwarded-For entry.
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


def _auth_environment() -> str:
    return os.getenv("WT_AUTH_ENV", os.getenv("WT_ENV", "development")).strip().lower()


def _rate_limit(request: Request) -> tuple[bool, int]:
    rule = _RATE_LIMIT_RULES.get(request.url.path)
    otp_route = request.url.path in {"/api/auth/otp/request", "/api/auth/otp/verify"}
    production_auth = _auth_environment() == "production"
    if rule and otp_route and production_auth:
        limit, window = rule
        return check_shared_rate_limit(request.url.path, _client_key(request), limit, window)
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
    try:
        allowed, retry_after = _rate_limit(request)
    except SharedRateLimitUnavailable as exc:
        logger.error("otp_rate_limit_unavailable error=%s", type(exc).__name__)
        return Response(
            "Authentication rate limiting is unavailable.",
            status_code=503,
            headers={"X-Request-ID": request_id},
        )
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
        and (not csrf_cookie or not csrf_header or not secrets.compare_digest(csrf_cookie, csrf_header))
    ):
        return Response("CSRF validation failed.", status_code=403, headers={"X-Request-ID": request_id})
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = str(duration_ms)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    csrf_token = csrf_cookie or secrets.token_urlsafe(24)
    response.set_cookie(
        "wt_csrf",
        csrf_token,
        httponly=False,
        secure=_auth_environment() == "production",
        samesite="None" if _auth_environment() == "production" else "Lax",
        max_age=8 * 60 * 60,
    )
    response.headers["X-CSRF-Token"] = csrf_token
    if _auth_environment() == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    logger.info(
        "http_request",
        extra={"request_id": request_id, "method": request.method, "path": request.url.path, "status_code": response.status_code, "duration_ms": duration_ms},
    )
    return response
runtime_env = os.getenv("WT_ENV", os.getenv("WT_AUTH_ENV", "development")).strip().lower()
configured_origins = {
    origin.strip()
    for value in (os.getenv("ALLOWED_ORIGINS", ""), os.getenv("FRONTEND_ORIGINS", ""), os.getenv("FRONTEND_ORIGIN", ""))
    for origin in value.split(",")
    if origin.strip()
}
development_origins = {
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:4173",
    "http://localhost:4174",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:4173",
    "http://127.0.0.1:4174",
}
production_origins = {
    "https://winged-tycoons-frontend.onrender.com",
    "https://wingedtycoons.com",
    "https://rfq.wingedtycoons.com",
    "https://www.wingedtycoons.com",
    "https://portal.wingedtycoons.com",
    "https://team.wingedtycoons.com",
}
allowed_origins = sorted(configured_origins | development_origins | (production_origins if runtime_env == "production" else set()))
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*", "X-CSRF-Token"],
)

# API Schemas
class IntakeRequest(BaseModel):
    raw_text: str = Field(..., description="Raw email or RFQ text submitted by customer")
    customer_name: Optional[str] = Field(None, description="Customer company or contact name")
    customer_email: Optional[str] = Field(None, description="Customer email for quote updates")
    reply_to: Optional[str] = Field(None, description="Original email message ID for same-thread replies")
    customer_country: Optional[str] = Field(None, description="Customer or destination country for export screening")
    attachment_ids: List[str] = Field(default_factory=list, description="Previously uploaded compliance attachment IDs")

class OtpRequest(BaseModel):
    email: str
    role: str
    full_name: str = ""

class OtpVerifyRequest(BaseModel):
    challenge_id: str
    code: str


class EmployeeProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    job_title: str = Field(min_length=1, max_length=120)


class EmployeePresenceUpdate(BaseModel):
    is_online: bool


class EmployeeClockAction(BaseModel):
    action: Literal["clock_in", "clock_out"]

class LoginResponse(BaseModel):
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
    condition: Optional[str] = None

class CustomerQuote(BaseModel):
    id: str
    rfq_id: str
    subtotal: float
    shipping_cost: float
    total_amount: float
    status: str
    lead_time_days: Optional[int] = None
    valid_until: Optional[str] = None

class CustomerQuoteDetails(BaseModel):
    quote: CustomerQuote
    items: List[CustomerQuoteItem]
    rfq_status: Optional[str] = None

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
    expected_version: Optional[int] = Field(None, ge=1)

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
    attachment_ids: List[str] = Field(default_factory=list)

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

class FailedIntakeResetRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000)

class TraceDecisionRequest(BaseModel):
    decision: str = Field(..., pattern="^(certify|reject|rescan|freeze)$")
    reason: Optional[str] = None

class ExtractionReviewDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    operator_name: Optional[str] = None
    comments: Optional[str] = None
    approved_extraction: Optional[Dict[str, Any]] = None

class InternalCommandRequest(BaseModel):
    command: str = Field(..., pattern="^(add_to_quote|issue_po|document_audit|generate_quote|split_po|escalate_aog|print_tags|generate_stamps)$")
    entity_id: str = Field(..., min_length=1)
    details: Optional[str] = None

class VoiceToolRequest(BaseModel):
    part_number: Optional[str] = None
    rfq_or_order_id: Optional[str] = None
    issue_type: Optional[str] = None
    details: Optional[str] = None

class VoiceSessionRequest(BaseModel):
    language: Literal["en", "es", "fr", "de", "pt", "it", "ja", "zh", "ko", "nl", "ar", "hi"] = "en"

VOICE_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "name": "check_inventory_availability",
        "description": "Search aerospace stock by exact or partial part number. Quote only the returned quantity, condition, price, and lead time.",
        "parameters": {
            "type": "object",
            "properties": {"part_number": {"type": "string", "description": "Aircraft part number or partial part number"}},
            "required": ["part_number"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_order_status",
        "description": "Look up the current status, tracking details, or operator review notice for an RFQ or order.",
        "parameters": {
            "type": "object",
            "properties": {"rfq_or_order_id": {"type": "string", "description": "RFQ or order identifier"}},
            "required": ["rfq_or_order_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "log_customer_concern",
        "description": "Record a concern or quote follow-up. Export-controlled, non-USD, or ambiguous requests are routed to an operator.",
        "parameters": {
            "type": "object",
            "properties": {
                "issue_type": {"type": "string"},
                "details": {"type": "string"},
                "part_number": {"type": "string"},
            },
            "required": ["issue_type", "details", "part_number"],
            "additionalProperties": False,
        },
    },
]

# Endpoints

@app.on_event("startup")
async def initialize_local_voice_recordings():
    if AUTH_STORAGE_BACKEND == "postgres":
        await asyncio.to_thread(init_auth_db)
    production = os.getenv("WT_ENV", os.getenv("WT_AUTH_ENV", "development")).strip().lower() == "production"
    if production and _auth_environment() != "production":
        raise RuntimeError("WT_AUTH_ENV must be production when WT_ENV is production.")
    runtime_enabled = os.getenv("OPERATIONAL_POSTGRES_RUNTIME_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    if production and runtime_enabled:
        await preflight_database()
    try:
        await asyncio.to_thread(initialize_voice_media)
    except Exception as exc:
        logger.warning("voice_media_initialization_failed error=%s", type(exc).__name__)


@app.post("/api/auth/otp/request")
async def otp_request(request: OtpRequest):
    requested_role = request.role.strip().upper()
    if requested_role in {"INTERNAL", "ROLE_INTERNAL"} and _auth_environment() != "production":
        raise HTTPException(
            status_code=503,
            detail="Internal email sign-in is unavailable until WT_AUTH_ENV=production is configured.",
        )
    if _auth_environment() == "production":
        try:
            allowed, retry_after = check_shared_rate_limit(
                "otp-request-email",
                request.email.strip().lower(),
                MAX_OTP_REQUESTS_PER_HOUR,
                3600,
            )
        except SharedRateLimitUnavailable as exc:
            logger.error("otp_email_rate_limit_unavailable error=%s", type(exc).__name__)
            raise HTTPException(503, "Authentication rate limiting is unavailable.") from exc
        if not allowed:
            raise HTTPException(
                429,
                "Too many OTP requests. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )
    challenge_id, code = request_otp(request.email, request.role, request.full_name)
    response = {"challenge_id": challenge_id, "message": "If eligible, an OTP has been sent."}
    auth_env = _auth_environment()
    if auth_env == "production":
        try:
            send_otp_email(request.email, code)
        except Exception as exc:
            logger.exception("otp_delivery_failed recipient_domain=%s error=%s", request.email.rsplit("@", 1)[-1], type(exc).__name__)
            raise HTTPException(
                status_code=503,
                detail="The verification email service is temporarily unavailable. Please try again or contact support.",
            ) from exc
    elif auth_env == "development":
        response["development_otp"] = code
    else:
        raise HTTPException(status_code=500, detail="WT_AUTH_ENV must be 'development' or 'production'.")
    return response

@app.post("/api/auth/otp/verify", response_model=LoginResponse)
async def otp_verify(request: OtpVerifyRequest, response: Response):
    result = verify_otp(request.challenge_id, request.code)
    response.status_code = 200
    response.headers["Cache-Control"] = "no-store"
    auth_env = _auth_environment()
    response.set_cookie(
        key="wt_session",
        value=result["access_token"],
        httponly=True,
        secure=auth_env == "production",
        samesite="None" if auth_env == "production" else "Lax",
        max_age=8 * 60 * 60,
    )
    return LoginResponse(
        role=result["role"],
        email=result["email"],
    )

@app.get("/api/auth/session")
async def auth_session(user: dict = Depends(current_user)):
    return {"email": user["email"], "role": user["role"]}

@app.post("/api/auth/logout", status_code=204)
async def logout(request: Request, response: Response):
    revoke_session(request.cookies.get("wt_session"))
    production = _auth_environment() == "production"
    response.delete_cookie(
        "wt_session",
        secure=production,
        httponly=True,
        samesite="None" if production else "Lax",
    )


@app.get("/api/auth/csrf")
async def auth_csrf():
    return {"status": "ok"}


@app.get("/api/internal/profile")
async def employee_profile(user: dict = Depends(require_roles("ROLE_INTERNAL", "ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING"))):
    async with employee_session() as session:
        return await get_profile(session, user)


@app.patch("/api/internal/profile")
async def employee_profile_update(
    request: EmployeeProfileUpdate,
    user: dict = Depends(require_roles("ROLE_INTERNAL", "ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING")),
):
    display_name = request.display_name.strip()
    job_title = request.job_title.strip()
    if not display_name or not job_title:
        raise HTTPException(status_code=422, detail="Display name and job title cannot be blank.")
    async with employee_session() as session:
        return await update_profile(session, user, display_name, job_title)


@app.put("/api/internal/profile/presence")
async def employee_presence_update(
    request: EmployeePresenceUpdate,
    user: dict = Depends(require_roles("ROLE_INTERNAL", "ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING")),
):
    async with employee_session() as session:
        return await set_presence(session, user, request.is_online)


@app.post("/api/internal/profile/clock")
async def employee_clock_action(
    request: EmployeeClockAction,
    user: dict = Depends(require_roles("ROLE_INTERNAL", "ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING")),
):
    try:
        async with employee_session() as session:
            profile = await record_clock_event(session, user, request.action)
            return profile
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/internal/work-hours")
async def employee_work_hours(
    month: str,
    user: dict = Depends(require_roles("ROLE_INTERNAL", "ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING")),
):
    try:
        async with employee_session() as session:
            await get_profile(session, user)
            report = await work_hours_report(session, month, user["id"])
            return report["employees"][0] if report["employees"] else {
                "month": month, "email": user["email"], "display_name": user.get("full_name", ""),
                "job_title": "", "is_online": False, "total_seconds": 0, "daily_seconds": {},
            }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/internal/hr/work-hours")
async def hr_work_hours_report(
    month: str,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER")),
):
    try:
        async with employee_session() as session:
            return await work_hours_report(session, month)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

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
    postgres_url = os.getenv("DATABASE_URL", "").strip()
    production = os.getenv("WT_ENV", os.getenv("WT_AUTH_ENV", "development")).strip().lower() == "production"
    postgres_healthy = False
    repository_checks = None
    migration_status = None
    if production and not postgres_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is required in production.")
    if postgres_url:
        engine = None
        try:
            engine = create_engine_from_environment()
            await preflight_database(engine)
            postgres_healthy = True
            migration_status = await check_migration_state(engine)
            async with session_scope(engine) as session:
                repositories = create_operational_repositories(session)
                repository_checks = await repositories.check_readiness()
                if production:
                    await db_service.list_rfqs_async(repositories)
        except Exception as exc:
            if production:
                raise HTTPException(status_code=503, detail=f"PostgreSQL not ready: {type(exc).__name__}") from exc
        finally:
            if engine is not None:
                await engine.dispose()
    if not production:
        try:
            db_service.list_rfqs()
        except Exception as exc:
            logger.error("readiness_database_check_failed", extra={"error_type": type(exc).__name__})
            raise HTTPException(status_code=503, detail="Database readiness check failed.") from exc
    persistence = persistence_status(
        postgres_healthy=postgres_healthy,
        repository_checks=repository_checks,
        migration_status=migration_status,
    )
    postgresql_mirroring = bool(persistence["inventory_postgres_mirror_enabled"])
    operational_postgres_cutover_ready = bool(
        persistence.get("operational_postgres_cutover_ready")
    )
    if production and not (postgresql_mirroring and operational_postgres_cutover_ready):
        raise HTTPException(
            status_code=503,
            detail=(
                "Production remains disabled until inventory mirroring and the full operational "
                "RFQ/supplier/quote repositories are PostgreSQL-backed. Review/telemetry persistence "
                "alone does not enable the workflow."
            ),
        )
    return {
        "status": "ready",
        "database": {"healthy": True},
        "postgresql_mirroring": postgresql_mirroring,
        "persistence": persistence,
        **persistence,
    }


@app.post("/api/session")
async def create_realtime_session(
    request: VoiceSessionRequest,
    user: dict = Depends(require_roles("ROLE_CUSTOMER", "ROLE_INTERNAL", "ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING")),
):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="Voice service is not configured.")
    await asyncio.to_thread(initialize_voice_media)

    language_names = {
        "en": "English", "es": "Spanish", "fr": "French", "de": "German",
        "pt": "Portuguese", "it": "Italian", "ja": "Japanese", "zh": "Chinese",
        "ko": "Korean", "nl": "Dutch", "ar": "Arabic", "hi": "Hindi",
    }
    language_name = language_names[request.language]
    voice_id = os.getenv("OPENAI_REALTIME_VOICE_ID", "").strip()
    output_voice: str | dict[str, str] = {"id": voice_id} if voice_id else "marin"
    session_payload = {
        "type": "realtime",
        "model": os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2").strip(),
        "output_modalities": ["audio"],
        "instructions": (
            "You are Camila, Winged Tycoons' AI voice customer-service assistant, not a human. At the start, "
            f"briefly disclose that you are Camila, an AI assistant, and greet the customer in {language_name}. "
            f"Continue speaking in {language_name} unless the customer asks to switch languages. Be "
            "concise, professional, and precise. Use the inventory and order tools before stating "
            "availability, prices, lead times, or status. Prices are USD. Never promise stock or issue "
            "a binding quote. Route export-controlled, non-USD, ambiguous, or unresolved requests to "
            "an operator using log_customer_concern, and clearly tell the caller their request is being reviewed."
        ),
        "audio": {
            "input": {
                "transcription": {"model": "gpt-4o-transcribe", "language": request.language},
                "turn_detection": {"type": "semantic_vad", "interrupt_response": True},
            },
            "output": {"voice": output_voice},
        },
        "tools": VOICE_TOOL_DEFINITIONS,
        "tool_choice": "auto",
    }
    session_request = {
        "expires_after": {"anchor": "created_at", "seconds": 600},
        "session": session_payload,
    }
    session_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "OpenAI-Safety-Identifier": hashlib.sha256(str(user.get("email", "")).lower().encode()).hexdigest(),
    }
    try:
        response = await asyncio.to_thread(
            requests.post,
            "https://api.openai.com/v1/realtime/client_secrets",
            headers=session_headers,
            json=session_request,
            timeout=20,
        )
        error_text = str(getattr(response, "text", "")).lower()
        custom_voice_rejected = voice_id and response.status_code in {400, 404} and (
            not error_text
            or "voice" in error_text
            or "not found" in error_text
            or "not available" in error_text
            or "unsupported" in error_text
        )
        if custom_voice_rejected:
            logger.warning("realtime_custom_voice_rejected status=%s fallback=builtin", response.status_code)
            session_payload["audio"]["output"]["voice"] = "marin"
            response = await asyncio.to_thread(
                requests.post,
                "https://api.openai.com/v1/realtime/client_secrets",
                headers=session_headers,
                json=session_request,
                timeout=20,
            )
        if response.status_code >= 400:
            logger.warning("realtime_session_create_failed status=%s", response.status_code)
            raise HTTPException(status_code=502, detail="Unable to start the voice session.")
        session = response.json()
    except requests.RequestException as exc:
        logger.warning("realtime_session_request_failed error=%s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Unable to reach the voice service.") from exc

    ephemeral_key = session.get("value")
    if not ephemeral_key:
        logger.warning("realtime_session_missing_ephemeral_key")
        raise HTTPException(status_code=502, detail="Voice service returned an invalid session.")
    return {"client_secret": ephemeral_key, "model": session_payload["model"]}


async def _voice_inventory_records(session) -> list[InventoryItem]:
    if session is None:
        return list(db_service.inventory.values())
    records = await create_operational_repositories(session).records.list("inventory")
    return [InventoryItem.model_validate(payload) for payload in records.values()]


@app.get("/api/voice/dashboard")
async def voice_dashboard(
    _user: dict = Depends(require_roles("ROLE_INTERNAL", "ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING")),
    session=Depends(get_async_db),
):
    rfqs = (
        db_service.list_rfqs()
        if session is None
        else await db_service.list_rfqs_async(create_operational_repositories(session))
    )
    inventory = await _voice_inventory_records(session)
    return get_voice_dashboard(rfqs, inventory)


@app.post("/api/voice/tools/{tool_name}")
async def execute_voice_tool(
    tool_name: str,
    request: VoiceToolRequest,
    user: dict = Depends(require_roles("ROLE_CUSTOMER", "ROLE_INTERNAL", "ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING")),
    session=Depends(get_async_db),
):
    if tool_name == "check_inventory_availability":
        inventory = await _voice_inventory_records(session)
        return check_inventory_availability(request.part_number or "", inventory)
    if tool_name == "get_order_status":
        rfqs = (
            db_service.list_rfqs()
            if session is None
            else await db_service.list_rfqs_async(create_operational_repositories(session))
        )
        if user.get("role") == "ROLE_CUSTOMER":
            return get_customer_order_status(
                request.rfq_or_order_id or "",
                user.get("email", ""),
                rfqs,
            )
        return get_order_status(request.rfq_or_order_id or "", rfqs)
    if tool_name == "log_customer_concern":
        return log_customer_concern(
            request.issue_type or "unspecified",
            request.details or "",
            request.part_number or "",
            user.get("email", "") if user.get("role") == "ROLE_CUSTOMER" else "",
        )
    raise HTTPException(status_code=404, detail="Unknown voice tool.")


@app.get("/api/attachments/{attachment_id}")
async def download_attachment(attachment_id: str, user: dict = Depends(current_user)):
    """Download an accepted attachment without exposing arbitrary filesystem paths."""
    if user["role"] not in {"ROLE_CUSTOMER", "ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions.")
    if user["role"] == ROLE_CUSTOMER:
        raise HTTPException(status_code=403, detail="Customer attachment downloads are not available.")

    attachment_path = attachment_service.get_stored_path(attachment_id)
    if attachment_path is None:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    return FileResponse(attachment_path, filename=attachment_path.name)


@app.post("/api/attachments")
async def upload_attachment(file: UploadFile = File(...), user: dict = Depends(current_user)):
    """Validate and store a customer attachment before RFQ submission."""
    if user["role"] not in {"ROLE_CUSTOMER", "ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions.")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Attachment filename is required.")
    record = attachment_service.validate_and_store(
        file.filename,
        file.content_type or "application/octet-stream",
        file.file,
    )
    if record.status != "ACCEPTED":
        raise HTTPException(status_code=400, detail=record.warning or "Attachment rejected.")
    return {
        "attachment_id": record.attachment_id,
        "filename": record.filename,
        "content_type": record.content_type,
        "size_bytes": record.size_bytes,
        "status": record.status,
    }

@app.post("/api/rfqs/intake", response_model=IntakeResponse)
async def submit_rfq(
    request: IntakeRequest,
    user: dict = Depends(current_user),
    session=Depends(get_async_db),
):
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
        
    if session is None:
        rfq = db_service.create_rfq(
            customer_name=customer_name,
            customer_email=customer_email,
            raw_text=request.raw_text,
            thread_id=request.reply_to,
        )
    else:
        rfq = RFQ(
            id=f"RFQ-{uuid.uuid4().hex[:6].upper()}",
            customer_name=customer_name,
            customer_email=customer_email,
            status="Intake",
            raw_text=request.raw_text,
            thread_id=request.reply_to,
        )
        await RFQRepository(session).create_from_payload(rfq.model_dump(mode="json"))
        session.add(AuditLogRecord(
            rfq_id=rfq.id,
            agent_name="GatewayAPI",
            action_type="intake_submission",
            message=f"RFQ submitted successfully for customer '{customer_name}'.",
            status="SUCCESS",
        ))
        if request.attachment_ids:
            session.add(AuditLogRecord(
                rfq_id=rfq.id,
                agent_name="AttachmentService",
                action_type="attachments_linked",
                message=f"Linked {len(request.attachment_ids)} customer attachment(s) to the RFQ.",
                status="SUCCESS",
                payload_json=json.dumps({"attachment_ids": request.attachment_ids}),
            ))
        await session.commit()

    if session is None:
        db_service.add_audit_log(
            rfq.id, "GatewayAPI", "intake_submission",
            f"RFQ submitted successfully for customer '{customer_name}'."
        )
        if request.attachment_ids:
            db_service.add_audit_log(
                rfq.id,
                "AttachmentService",
                "attachments_linked",
                f"Linked {len(request.attachment_ids)} customer attachment(s) to the RFQ.",
                "SUCCESS",
                json.dumps({"attachment_ids": request.attachment_ids}),
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
        orchestration_service.block_rfq_for_compliance(rfq.id, screening)
        return IntakeResponse(
            rfq_id=rfq.id,
            status="Blocked_Compliance_Review",
            message="RFQ blocked pending export-control compliance review.",
        )
    
    # Run the pipeline synchronously to make parsing results immediately available in MVP
    pipeline_res = await orchestration_service.process_rfq_pipeline(rfq.id)
    
    status = pipeline_res.get("status", rfq.status)
    error = pipeline_res.get("error", "")
    
    if status == "Quote_Sent":
        msg = f"Thank you! Your quote for {rfq.id} has been emailed to {customer_email}."
    elif status == "Quote_Dispatch_Pending":
        msg = f"Thank you! Your quote for {rfq.id} is ready and on its way to {customer_email}."
    elif "Failed" in status or "Halted" in status or "Warning" in status:
        logger.warning("RFQ %s pipeline issue: %s", rfq.id, error)
        msg = f"Thank you! We received {rfq.id}. Our team is reviewing it personally and will email you shortly."
    else:
        msg = f"Thank you! We received {rfq.id}. Our team is checking availability and pricing and will email your quote to {customer_email} shortly."
        
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

@app.post("/api/internal/rfqs/{rfq_id}/reset-intake")
async def reset_failed_intake(
    rfq_id: str,
    request: FailedIntakeResetRequest,
    user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER")),
    session=Depends(get_async_db),
):
    reason = request.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A reset reason is required.")

    audit_message = f"Failed intake reset to Intake by {user['email']}. Reason: {reason}"
    if session is not None:
        repositories = create_operational_repositories(session)
        payload = await repositories.rfq.get_operational_record("rfqs", rfq_id)
        record = await repositories.rfq.get(rfq_id) if payload is None else None
        if payload is None and record is None:
            raise HTTPException(status_code=404, detail="RFQ not found.")
        status = payload.get("status") if payload is not None else record.status
        if status != "Intake_Failed":
            raise HTTPException(
                status_code=409,
                detail="Only Intake_Failed RFQs can be reset. Human-review RFQs must be resolved through their review queue.",
            )
        try:
            updated = await repositories.rfq.reset_failed_intake(rfq_id, audit_message)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not updated:
            raise HTTPException(status_code=404, detail="RFQ not found.")
    else:
        rfq = db_service.get_rfq(rfq_id)
        if rfq is None:
            raise HTTPException(status_code=404, detail="RFQ not found.")
        if rfq.status != "Intake_Failed":
            raise HTTPException(
                status_code=409,
                detail="Only Intake_Failed RFQs can be reset. Human-review RFQs must be resolved through their review queue.",
            )
        transaction = operations_store.transaction() if operations_store.storage_engine == "postgresql" else nullcontext()
        with transaction:
            updated = db_service.update_rfq_status(rfq_id, "Intake")
            if updated is None:
                raise HTTPException(status_code=404, detail="RFQ not found.")
            db_service.add_audit_log(
                rfq_id,
                "AutomationControl",
                "intake_reset",
                audit_message,
                "WARNING",
            )
    return {"rfq_id": rfq_id, "status": "Intake", "reset_by": user["email"], "reason": reason}

@app.post("/api/internal/rfqs/{rfq_id}/automation")
async def set_automation_pause(
    rfq_id: str,
    request: AutomationPauseRequest,
    user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER")),
    session=Depends(get_async_db),
):
    if session is not None:
        result = await create_operational_repositories(session).rfq.set_automation_paused(
            rfq_id, request.paused, request.reason, user["email"]
        )
        if result is None:
            raise HTTPException(status_code=404, detail=f"RFQ {rfq_id} not found.")
        return result
    try:
        return orchestration_service.set_automation_pause(
            rfq_id, request.paused, request.reason, user["email"]
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.post("/api/internal/rfqs/{rfq_id}/trace-decision")
async def record_trace_decision(
    rfq_id: str,
    request: TraceDecisionRequest,
    user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING")),
    session=Depends(get_async_db),
):
    reason = request.reason or f"Trace decision '{request.decision}' recorded by {user['email']}."
    if session is not None:
        result = await create_operational_repositories(session).rfq.record_trace_decision(
            rfq_id, request.decision, reason
        )
        if result is None:
            raise HTTPException(status_code=404, detail=f"RFQ {rfq_id} not found.")
        return result
    try:
        return orchestration_service.record_trace_decision(
            rfq_id, request.decision, reason, user["email"]
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.get("/api/internal/automation-events")
async def list_automation_events(
    status: Optional[str] = None,
    limit: int = 100,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING")),
):
    return operations_store.list_automation_events(status=status, limit=limit)


@app.get("/api/internal/extraction-reviews")
async def list_extraction_reviews(
    status: str = "PENDING",
    limit: int = 100,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING")),
):
    return operations_store.list_operator_reviews(status=status.upper(), limit=limit)


@app.get("/api/internal/llm/telemetry")
async def list_llm_telemetry(
    task: Optional[str] = None,
    limit: int = 100,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER")),
):
    return operations_store.list_llm_telemetry(task=task, limit=limit)


@app.get("/api/internal/extraction-reviews/{review_id}")
async def get_extraction_review(
    review_id: str,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING")),
):
    review = operations_store.get_operator_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Extraction review not found.")
    return review


@app.post("/api/internal/extraction-reviews/{review_id}/decision")
async def decide_extraction_review(
    review_id: str,
    request: ExtractionReviewDecisionRequest,
    user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING")),
):
    review = operations_store.get_operator_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Extraction review not found.")
    operator = (request.operator_name or user["email"]).strip()
    try:
        return await orchestration_service.decide_extraction_review(
            review=review,
            decision=request.decision,
            operator=operator,
            comments=request.comments,
            approved_extraction=request.approved_extraction,
        )
    except ReviewDecisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewDecisionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Review decision could not be completed.") from exc

@app.post("/api/internal/commands")
async def execute_internal_command(
    request: InternalCommandRequest,
    user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING")),
):
    message = f"Command '{request.command}' recorded for {request.entity_id}."
    db_service.add_audit_log(
        request.entity_id,
        "InternalCommand",
        request.command,
        f"{message} Operator: {user['email']}." + (f" Details: {request.details}" if request.details else ""),
        "WARNING" if request.command in {"escalate_aog", "split_po"} else "SUCCESS",
    )
    return {"command": request.command, "entity_id": request.entity_id, "status": "RECORDED", "message": message}


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
    user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING", "ROLE_INTERNAL")),
):
    """Return status-only health for the shared sales and purchasing mailboxes."""
    health = health_check_mailboxes(["sales", "purchasing"])
    return {
        "sales_mailbox": health.get("sales", {}).get("status", "unknown"),
        "purchasing_mailbox": health.get("purchasing", {}).get("status", "unknown"),
        "authenticated_user": user["email"],
    }

@app.get("/api/rfqs", response_model=List[RFQ])
async def list_rfqs(
    user: dict = Depends(current_user),
    session=Depends(get_async_db),
):
    """
    Retrieves all RFQs.
    """
    if session is None:
        rfqs = db_service.list_rfqs()
    else:
        rfqs = await db_service.list_rfqs_async(create_operational_repositories(session))
    if user["role"] == "ROLE_CUSTOMER":
        return [rfq for rfq in rfqs if rfq.customer_email.lower() == user["email"].lower()]
    if user["role"] not in ("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING"):
        raise HTTPException(status_code=403, detail="Insufficient permissions.")
    return rfqs

@app.get("/api/rfqs/{rfq_id}")
async def get_rfq_detail(
    rfq_id: str,
    user: dict = Depends(current_user),
    session=Depends(get_async_db),
) -> CustomerRFQDetail | dict:
    """
    Retrieves complete status details, items, audit logs, and associated quotes.
    """
    async_repositories = create_operational_repositories(session) if session is not None else None
    if async_repositories is None:
        rfq = db_service.get_rfq(rfq_id)
    else:
        rfq_payload = await async_repositories.rfq.get_operational_record("rfqs", rfq_id)
        rfq_record = await async_repositories.rfq.get(rfq_id) if rfq_payload is None else None
        rfq = RFQ.model_validate(rfq_payload) if rfq_payload is not None else (
            RFQ(
                id=rfq_record.id,
                customer_name=rfq_record.customer_name,
                customer_email=rfq_record.customer_email,
                status=rfq_record.status,
                raw_text=rfq_record.raw_text,
                thread_id=rfq_record.thread_id,
                created_at=rfq_record.created_at,
            ) if rfq_record else None
        )
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found.")
    if user["role"] == "ROLE_CUSTOMER" and rfq.customer_email.lower() != user["email"].lower():
        raise HTTPException(status_code=403, detail="You can only access your own requests.")
        
    if async_repositories is None:
        items = db_service.get_rfq_items(rfq_id)
        quote = db_service.get_quote_by_rfq(rfq_id)
        quote_items = db_service.get_quote_items(quote.id) if quote else []
    else:
        item_records = await async_repositories.records.list_by_payload_value(
            "rfq_items", "rfq_id", rfq_id
        )
        items = [RFQItem.model_validate(value) for value in item_records.values()]
        quote_records = await async_repositories.records.list_by_payload_value(
            "quotes", "rfq_id", rfq_id
        )
        quote = next((Quote.model_validate(value) for value in quote_records.values()), None)
        quote_item_records = (
            await async_repositories.records.list_by_payload_value(
                "quote_items", "quote_id", quote.id
            )
            if quote else {}
        )
        quote_items = [QuoteItem.model_validate(value) for value in quote_item_records.values()]

    if user["role"] == "ROLE_CUSTOMER":
        quote_details = None
        if quote and quote.status == "Sent":
            quote_details = CustomerQuoteDetails(
                quote=CustomerQuote(
                    id=quote.id,
                    rfq_id=quote.rfq_id,
                    subtotal=quote.subtotal,
                    shipping_cost=quote.shipping_cost,
                    total_amount=quote.total_amount,
                    status=quote.status,
                    lead_time_days=quote.lead_time_days,
                    valid_until=quote.valid_until,
                ),
                rfq_status=rfq.status,
                items=[
                    CustomerQuoteItem(
                        part_number=item.part_number,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        certificate_type=item.certificate_type,
                        compliance_status=item.compliance_status,
                        condition=item.condition,
                    )
                    for item in quote_items
                ],
            )
        return CustomerRFQDetail(rfq=rfq, items=items, quote_details=quote_details)

    if user["role"] not in ("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING"):
        raise HTTPException(status_code=403, detail="Insufficient permissions.")

    logs = (
        db_service.get_audit_logs(rfq_id)
        if async_repositories is None
        else await db_service.get_audit_logs_async(async_repositories, rfq_id)
    )
    
    quote_details = None
    if quote:
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

@app.get("/api/quotes/{quote_id}", response_model=CustomerQuoteDetails)
async def get_customer_quote(
    quote_id: str,
    user: dict = Depends(current_user),
    session=Depends(get_async_db),
):
    if user["role"] != ROLE_CUSTOMER:
        raise HTTPException(status_code=403, detail="Customer access is required.")

    repositories = create_operational_repositories(session) if session is not None else None
    if repositories is None:
        quote = db_service.get_quote(quote_id)
        rfq = db_service.get_rfq(quote.rfq_id) if quote else None
        quote_items = db_service.get_quote_items(quote_id) if quote else []
    else:
        quote_payload = await repositories.quote.get_operational_record("quotes", quote_id)
        quote_record = quote_payload or await repositories.quote.get(quote_id)
        if quote_record is None:
            raise HTTPException(status_code=404, detail="Quote not found.")
        quote = (
            Quote.model_validate(quote_payload)
            if quote_payload is not None
            else Quote(
                id=quote_record.id,
                rfq_id=quote_record.rfq_id,
                subtotal=quote_record.subtotal,
                shipping_cost=quote_record.shipping_cost,
                total_amount=quote_record.total_amount,
                status=quote_record.status,
            )
        )
        rfq = await db_service.get_rfq_async(repositories, quote.rfq_id)
        item_records = await repositories.records.list_by_payload_value(
            "quote_items", "quote_id", quote_id
        )
        quote_items = [QuoteItem.model_validate(value) for value in item_records.values()]

    if quote is None or rfq is None:
        raise HTTPException(status_code=404, detail="Quote not found.")
    if rfq.customer_email.lower() != user["email"].lower():
        raise HTTPException(status_code=403, detail="You can only access your own quotes.")
    if quote.status != "Sent":
        raise HTTPException(status_code=404, detail="Quote not found.")

    return CustomerQuoteDetails(
        quote=CustomerQuote(
            id=quote.id,
            rfq_id=quote.rfq_id,
            subtotal=quote.subtotal,
            shipping_cost=quote.shipping_cost,
            total_amount=quote.total_amount,
            status=quote.status,
            lead_time_days=quote.lead_time_days,
            valid_until=quote.valid_until,
        ),
        rfq_status=rfq.status,
        items=[
            CustomerQuoteItem(
                part_number=item.part_number,
                quantity=item.quantity,
                unit_price=item.unit_price,
                certificate_type=item.certificate_type,
                compliance_status=item.compliance_status,
                condition=item.condition,
            )
            for item in quote_items
        ],
    )

@app.post("/api/quotes/{quote_id}/approve")
async def approve_quote(
    quote_id: str,
    request: ApproveRequest,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES")),
    session=Depends(get_async_db),
):
    """
    Performs Human-in-the-Loop quote approval and sends final offer.
    Supports pricing overrides.
    """
    if session is not None:
        repositories = create_operational_repositories(session)
        result = await orchestration_service.approve_and_queue_quote_async(
            repositories,
            quote_id=quote_id,
            operator_name=request.operator_name,
            overrides=[
                {"quote_item_id": item.quote_item_id, "unit_price": item.unit_price}
                for item in request.items_override or []
            ],
            comments=request.comments,
            expected_version=request.expected_version,
        )
        if result.get("error"):
            raise HTTPException(
                status_code=int(result.get("status_code") or 409),
                detail=result["error"],
            )
        if not result.get("status") or result.get("error"):
            raise HTTPException(status_code=409, detail="Quote approval failed.")
        await session.commit()
        return result

    quote = db_service.get_quote(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found.")
        
    overrides_list = []
    if request.items_override:
        overrides_list = [{"quote_item_id": o.quote_item_id, "unit_price": o.unit_price} for o in request.items_override]
        
    try:
        res = await orchestration_service.approve_and_send_quote(
            quote_id=quote_id,
            operator_name=request.operator_name,
            overrides=overrides_list,
            comments=request.comments,
            expected_version=request.expected_version if request.expected_version is not None else quote.version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    
    # Use the status produced by orchestration; the original object is stale after approval.
    final_status = res.get("status")
    if not final_status or res.get("error"):
        raise HTTPException(status_code=409, detail=res.get("error", "Quote approval failed."))
    return res

@app.post("/api/quotes/{quote_id}/reject")
async def reject_quote(
    quote_id: str,
    request: RejectRequest,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES")),
    session=Depends(get_async_db),
):
    """
    Rejects proposal and shifts state.
    """
    repositories = create_operational_repositories(session) if session is not None else None
    quote = (
        db_service.get_quote(quote_id)
        if repositories is None
        else await repositories.quote.get_operational_record("quotes", quote_id)
        or await repositories.quote.get(quote_id)
    )
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found.")
    rfq_id = quote.rfq_id if hasattr(quote, "rfq_id") else quote.get("rfq_id")
    if repositories is None:
        result = orchestration_service.reject_quote(quote_id, request.operator_name, request.comments)
        if result.get("error"):
            raise HTTPException(status_code=409, detail=result["error"])
        return result

    rfq = await db_service.get_rfq_async(repositories, rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found.")
    rejected = await repositories.rfq.reject_quote(
        quote_id, rfq_id, request.operator_name, request.comments
    )
    if not rejected:
        raise HTTPException(status_code=409, detail="Quote state changed before rejection could be recorded.")
    await session.commit()
    return {"status": "Rejected", "quote_id": quote_id}

@app.post("/api/purchase-orders")
async def submit_purchase_order(
    request: PurchaseOrderRequest,
    user: dict = Depends(current_user),
    session=Depends(get_async_db),
):
    """Receive a customer PO and route its purchasing details to the human team."""
    repositories = create_operational_repositories(session) if session is not None else None
    quote = (
        db_service.get_quote(request.quote_id)
        if repositories is None
        else await repositories.quote.get_operational_record("quotes", request.quote_id)
        or await repositories.quote.get(request.quote_id)
    )
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found.")
    rfq_id = quote.rfq_id if hasattr(quote, "rfq_id") else quote.get("rfq_id")
    rfq = (
        db_service.get_rfq(rfq_id)
        if repositories is None
        else await db_service.get_rfq_async(repositories, rfq_id)
    )
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found.")
    if user["role"] == ROLE_CUSTOMER and rfq.customer_email.lower() != user["email"].lower():
        raise HTTPException(status_code=403, detail="You can only submit a purchase order for your own quote.")
    quote_status = quote.status if hasattr(quote, "status") else quote.get("status")
    if quote_status != "Sent":
        raise HTTPException(status_code=409, detail="This quote is not available for acceptance.")
    if rfq.status in {"Purchase_Order_Received", "Pending_PO_Review"}:
        raise HTTPException(status_code=409, detail="Purchase order already received for this RFQ.")

    customer_email = (
        rfq.customer_email
        if user["role"] == ROLE_CUSTOMER
        else request.customer_email or rfq.customer_email
    )
    if len(request.attachment_ids) != 3 or any(not attachment_id.strip() for attachment_id in request.attachment_ids):
        raise HTTPException(status_code=400, detail="Three signed documents are required: export certification, KYC form, and purchase order.")
    if len({attachment_id.strip().upper() for attachment_id in request.attachment_ids}) != 3:
        raise HTTPException(status_code=400, detail="Upload three separate signed document PDFs.")
    for attachment_id in request.attachment_ids:
        document_path = attachment_service.get_stored_path(attachment_id)
        if document_path is None or document_path.suffix.lower() != ".pdf":
            raise HTTPException(status_code=400, detail="Upload three accepted PDF documents before submitting the purchase order.")
        with document_path.open("rb") as document:
            if document.read(5) != b"%PDF-":
                raise HTTPException(status_code=400, detail="Each purchase-order document must be a valid PDF.")
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

    if repositories is None:
        quote_items = db_service.get_quote_items(request.quote_id)
    else:
        quote_item_records = await repositories.records.list_by_payload_value(
            "quote_items", "quote_id", request.quote_id
        )
        quote_items = list(quote_item_records.values())
    internal_items = []
    supplier_groups: Dict[str, Dict[str, Any]] = {}
    for item in quote_items:
        part_number = item.part_number if hasattr(item, "part_number") else item.get("part_number", "")
        item_quantity = item.quantity if hasattr(item, "quantity") else item.get("quantity", 1)
        item_unit_cost = item.unit_cost if hasattr(item, "unit_cost") else item.get("unit_cost", 0)
        item_unit_price = item.unit_price if hasattr(item, "unit_price") else item.get("unit_price", 0)
        offers = (
            operations_store.get_supplier_offers(part_number, item_quantity)
            if repositories is None and operations_store.storage_engine == "postgresql"
            else supplier_db.find_supplier_offers(part_number, quantity_needed=item_quantity)
            if repositories is None
            else await repositories.supplier.offers_for_part(part_number, quantity_needed=item_quantity)
        )
        selected = next(
            (offer for offer in offers if abs(float(offer.get("unit_cost") or 0) - float(item_unit_cost or 0)) < 0.01),
            offers[0] if offers else None,
        )
        supplier_name = selected.get("supplier_name") if selected else "Internal inventory"
        supplier_email = selected.get("supplier_email") if selected else ""
        internal_item = {
            "part_number": part_number,
            "quantity": item_quantity,
            "unit_price": item_unit_price,
            "supplier_name": supplier_name,
            "supplier_email": supplier_email,
            "supplier_unit_cost": float(selected.get("unit_cost") or item_unit_cost or 0) if selected else float(item_unit_cost or 0),
        }
        internal_items.append(internal_item)
        if supplier_email:
            supplier_groups.setdefault(supplier_email, {"supplier_name": supplier_name, "items": []})["items"].append(internal_item)

    recipient = os.getenv("CAMILA_NOTIFICATION_EMAIL", os.getenv("PURCHASE_ORDER_NOTIFICATION_EMAIL", "camila@wingedtycoons.com"))
    customer_name = rfq.customer_name if hasattr(rfq, "customer_name") else rfq.get("customer_name", "")
    total_amount = quote.total_amount if hasattr(quote, "total_amount") else quote.get("total_amount", 0)
    review_url = os.getenv("SALES_DASHBOARD_URL") or os.getenv("PUBLIC_APP_URL", "http://localhost:3000")
    if repositories is not None:
        requested_po_id = f"PO-{uuid.uuid4().hex[:20].upper()}"
        accepted = await repositories.rfq.receive_purchase_order(
            po_id=requested_po_id,
            po_number=request.po_number,
            quote_id=request.quote_id,
            rfq_id=rfq.id,
            customer_email=customer_email,
            total_amount=float(total_amount or 0),
            attachment_metadata=[{"attachment_id": value} for value in request.attachment_ids],
        )
        if not accepted:
            raise HTTPException(status_code=409, detail="Purchase order already received.")
        notification = await communication_service.notify_purchase_order_async(
            repositories,
            recipient=recipient,
            po_number=request.po_number,
            customer_name=customer_name,
            customer_email=customer_email,
            quote_id=request.quote_id,
            items=internal_items,
            review_url=review_url,
        )
        await session.commit()
    else:
        transaction = operations_store.transaction() if operations_store.storage_engine == "postgresql" else nullcontext()
        with transaction:
            requested_po_id = f"PO-{uuid.uuid4().hex[:20].upper()}"
            purchase_order = operations_store.record_purchase_order(
                po_id=requested_po_id,
                po_number=request.po_number,
                customer_email=customer_email,
                total_amount=float(total_amount or 0),
                status="Pending_PO_Review",
                quote_id=request.quote_id,
                rfq_id=rfq.id,
                received_message_id=None,
                attachment_metadata=[{"attachment_id": value} for value in request.attachment_ids],
            )
            if purchase_order.get("id") and purchase_order["id"] != requested_po_id:
                raise HTTPException(status_code=409, detail="Purchase order already received.")
            notification = communication_service.notify_purchase_order(
                recipient=recipient,
                po_number=request.po_number,
                customer_name=customer_name,
                customer_email=customer_email,
                quote_id=request.quote_id,
                items=internal_items,
                review_url=review_url,
            )
            orchestration_service.mark_purchase_order_received(rfq.id, request.po_number, request.attachment_ids)
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
    session=Depends(get_async_db),
):
    """Release a previously held PO for downstream purchasing work."""
    repositories = create_operational_repositories(session) if session is not None else None
    quote = (
        db_service.get_quote(quote_id)
        if repositories is None
        else await repositories.quote.get_operational_record("quotes", quote_id)
        or await repositories.quote.get(quote_id)
    )
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found.")
    rfq_id = quote.rfq_id if hasattr(quote, "rfq_id") else quote.get("rfq_id")
    rfq = (
        db_service.get_rfq(rfq_id)
        if repositories is None
        else await db_service.get_rfq_async(repositories, rfq_id)
    )
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found.")
    if rfq.status != "Pending_PO_Review":
        raise HTTPException(status_code=409, detail="PO is not waiting for human review.")

    if repositories is None:
        orchestration_service.approve_purchase_order(rfq.id, request.operator_name, request.comments)
    else:
        approved = await repositories.rfq.approve_purchase_order(
            rfq.id, quote_id, request.operator_name, request.comments
        )
        if not approved:
            raise HTTPException(status_code=409, detail="PO is no longer waiting for human review.")
        await session.commit()
    return {"status": "Purchase_Order_Received", "quote_id": quote_id, "rfq_id": rfq.id}

def _detect_carrier_tracking(value: str):
    """Recognize public carrier tracking numbers and return (carrier, number, live tracking URL)."""
    number = re.sub(r"[\s-]", "", value or "").upper()
    if re.fullmatch(r"1Z[0-9A-Z]{16}", number):
        return "UPS", number, f"https://www.ups.com/track?tracknum={number}"
    if re.fullmatch(r"\d{12}|\d{15}|\d{20}|\d{22}", number) and not number.startswith(("94", "93", "92")):
        return "FedEx", number, f"https://www.fedex.com/fedextrack/?trknbr={number}"
    if re.fullmatch(r"9[234]\d{18,20}|[A-Z]{2}\d{9}US", number):
        return "USPS", number, f"https://tools.usps.com/go/TrackConfirmAction?tLabels={number}"
    if re.fullmatch(r"\d{10,11}", number):
        return "DHL", number, f"https://www.dhl.com/global-en/home/tracking/tracking-express.html?tracking-id={number}"
    return None

@app.get("/api/shipments/track/{public_token}")
async def track_shipment(public_token: str, session=Depends(get_async_db)):
    """Return customer-safe shipment status using an opaque tracking token."""
    repositories = create_operational_repositories(session) if session is not None else None
    shipment = (
        db_service.get_shipment_by_token(public_token)
        if repositories is None
        else await db_service.get_shipment_by_token_async(repositories, public_token)
    )
    if not shipment:
        carrier_match = _detect_carrier_tracking(public_token)
        if carrier_match:
            carrier, number, url = carrier_match
            return {
                "shipment_id": number,
                "status": f"In transit with {carrier}",
                "part_numbers": [],
                "quantity": 0,
                "carrier": carrier,
                "tracking_number": number,
                "tracking_url": url,
                "estimated_delivery": None,
                "events": [],
            }
        raise HTTPException(status_code=404, detail="We couldn't find that shipment. Please check the tracking number.")
    events = (
        db_service.get_shipment_events(shipment.id)
        if repositories is None
        else await db_service.get_shipment_events_async(repositories, shipment.id)
    )
    return {
        "shipment_id": shipment.id,
        "status": shipment.status,
        "part_numbers": shipment.part_numbers,
        "quantity": shipment.quantity,
        "carrier": shipment.carrier,
        "tracking_number": shipment.tracking_number,
        "estimated_delivery": shipment.estimated_delivery,
        "events": [event.model_dump(mode="json") for event in events],
    }

@app.post("/api/internal/shipments")
async def create_shipment(
    request: ShipmentCreateRequest,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING")),
    session=Depends(get_async_db),
):
    repositories = create_operational_repositories(session) if session is not None else None
    rfq = (
        db_service.get_rfq(request.rfq_id)
        if repositories is None
        else await db_service.get_rfq_async(repositories, request.rfq_id)
    )
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found.")
    if rfq.status == "Pending_PO_Review":
        raise HTTPException(status_code=409, detail="Fulfillment is blocked until the purchase order is approved by a human operator.")
    shipment_values = {
        "rfq_id": request.rfq_id,
        "quote_id": request.quote_id,
        "customer_email": rfq.customer_email,
        "part_numbers": request.part_numbers,
        "quantity": request.quantity,
        "public_token": secrets.token_urlsafe(24),
    }
    if repositories is None:
        shipment = db_service.create_shipment(**shipment_values)
        tracking_notification = communication_service.send_shipment_tracking_link(
            recipient=rfq.customer_email,
            shipment_id=shipment.id,
            public_token=shipment.public_token,
        )
    else:
        shipment = await db_service.create_shipment_async(repositories, **shipment_values)
        tracking_notification = await communication_service.send_shipment_tracking_link_async(
            repositories,
            recipient=rfq.customer_email,
            shipment_id=shipment.id,
            public_token=shipment.public_token,
        )
        await session.commit()
    return {
        "shipment_id": shipment.id,
        "tracking_url": f"/track/{shipment.public_token}",
        "status": shipment.status,
        "tracking_notification": tracking_notification["transmission_status"],
    }

@app.get("/api/internal/shipments")
async def list_shipments(
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING")),
    session=Depends(get_async_db),
):
    if session is None:
        return db_service.list_shipments()
    return await db_service.list_shipments_async(create_operational_repositories(session))

@app.post("/api/internal/shipments/{shipment_id}/events")
async def add_shipment_event(
    shipment_id: str,
    request: ShipmentEventRequest,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING")),
    session=Depends(get_async_db),
):
    if session is None:
        if not db_service.get_shipment(shipment_id):
            raise HTTPException(status_code=404, detail="Shipment not found.")
        event = db_service.add_shipment_event(shipment_id, request.status, request.location, request.description)
    else:
        repositories = create_operational_repositories(session)
        event = await db_service.add_shipment_event_async(
            repositories, shipment_id, request.status, request.location, request.description
        )
        if event is None:
            raise HTTPException(status_code=404, detail="Shipment not found.")
    return {"status": "updated", "event": event}

@app.post("/api/internal/shipments/{shipment_id}/tracking")
async def register_carrier_tracking(
    shipment_id: str,
    request: CarrierTrackingRequest,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING")),
    session=Depends(get_async_db),
):
    if session is None:
        shipment = db_service.update_shipment_tracking(
            shipment_id, request.carrier, request.tracking_number
        )
    else:
        repositories = create_operational_repositories(session)
        shipment = await db_service.update_shipment_tracking_async(
            repositories, shipment_id, request.carrier, request.tracking_number
        )
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
    session=Depends(get_async_db),
):
    repositories = create_operational_repositories(session) if session is not None else None
    shipment = (
        db_service.get_shipment(shipment_id)
        if repositories is None
        else await db_service.get_shipment_async(repositories, shipment_id)
    )
    if not shipment or not shipment.carrier or not shipment.tracking_number:
        raise HTTPException(status_code=404, detail="Shipment tracking is not registered.")
    payload = carrier_tracking_service.get_tracker(shipment.carrier, shipment.tracking_number)
    normalized = carrier_tracking_service.normalize_webhook(payload)
    event = (
        db_service.add_shipment_event(
            shipment_id, normalized["status"], normalized.get("location"), normalized["description"]
        )
        if repositories is None
        else await db_service.add_shipment_event_async(
            repositories, shipment_id, normalized["status"], normalized.get("location"), normalized["description"]
        )
    )
    return {"shipment_id": shipment_id, "event": event, "provider": payload}

@app.post("/api/internal/shipments/{shipment_id}/sms")
async def send_shipment_sms(
    shipment_id: str,
    request: ShipmentSmsRequest,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING", "ROLE_SALES")),
    session=Depends(get_async_db),
):
    shipment = (
        db_service.get_shipment(shipment_id)
        if session is None
        else await db_service.get_shipment_async(create_operational_repositories(session), shipment_id)
    )
    if not shipment:
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
    try:
        return orchestration_service.apply_signed_carrier_event(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.get("/api/catalog/search", response_model=List[CatalogItem])
async def search_catalog(query: str = "", condition: Optional[str] = None, _user: dict = Depends(require_roles("ROLE_CUSTOMER", "ROLE_ADMIN", "ROLE_MANAGER", "ROLE_SALES", "ROLE_PURCHASING"))):
    """Public, customer-safe catalog availability search.

    Deliberately omits internal costs, serial numbers, and warehouse locations.
    """
    normalized_query = query.strip().lower()
    if not normalized_query:
        return []
    normalized_condition = (condition or "").strip().upper()
    valid_conditions = {"NE", "FN", "NS", "OH", "SVC", "RP", "AR", "IN"}
    if normalized_condition and normalized_condition not in valid_conditions:
        raise HTTPException(status_code=400, detail="Condition must be NE, FN, NS, OH, SVC, RP, AR, or IN.")
    results = []
    seen_parts: set[tuple[str, str]] = set()
    for item in db_service.inventory.values():
        if normalized_query and normalized_query not in item.part_number.lower():
            continue
        if normalized_condition and item.condition_code.upper() != normalized_condition:
            continue
        key = (item.part_number.upper(), item.condition_code.upper())
        seen_parts.add(key)
        results.append(CatalogItem(
            part_number=item.part_number,
            condition_code=item.condition_code,
            quantity_available=item.quantity_available,
            certificate_type=item.certificate_type,
            has_full_trace=item.has_full_trace,
        ))
    if os.getenv("INVENTORY_INGESTION_POSTGRES_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            engine = create_engine_from_environment()
            try:
                async with session_scope(engine) as session:
                    postgres_results = await search_supplier_inventory(session, query=query, condition_code=normalized_condition or None)
            finally:
                await engine.dispose()
            for item in postgres_results:
                key = (str(item["part_number"]).upper(), str(item.get("condition_code") or "NE").upper())
                if key in seen_parts:
                    continue
                seen_parts.add(key)
                results.append(CatalogItem(
                    part_number=key[0],
                    condition_code=key[1],
                    quantity_available=int(item.get("quantity_available") or 0),
                    certificate_type=item.get("certificate_type") or "Available upon supplier confirmation",
                    has_full_trace=bool(item.get("has_full_trace")),
                ))
        except Exception:
            logger.exception("postgres_catalog_search_failed")
    supplier_offers = (
        operations_store.search_supplier_offers(query, normalized_condition or None)
        if operations_store.storage_engine == "postgresql"
        else supplier_db.search_supplier_offers(query, normalized_condition or None)
    )
    for offer in supplier_offers:
        key = (str(offer.get("part_number", "")).upper(), str(offer.get("condition_code") or "NE").upper())
        if key in seen_parts:
            continue
        results.append(CatalogItem(
            part_number=key[0],
            condition_code=key[1],
            quantity_available=int(offer.get("quantity_available") or 0),
            certificate_type=offer.get("certificate_type") or "Available upon supplier confirmation",
            has_full_trace=bool(offer.get("certificate_type")),
        ))
    return results

@app.get("/api/inventory")
async def get_inventory(
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING")),
    session=Depends(get_async_db),
):
    """
    Fetch internal stock inventory.
    """
    if session is None:
        try:
            catalog = operations_store.list_inventory_catalog(500)
        except Exception:
            logger.exception("Inventory catalog query failed")
            catalog = []
        if catalog:
            return [
                InventoryItem(
                    id=str(row.get("id")),
                    part_number=str(row.get("part_number") or ""),
                    serial_number=str(row.get("description") or "")[:120],
                    quantity_available=int(row.get("quantity_available") or 0),
                    condition_code=str(row.get("condition_code") or "AR"),
                    warehouse_location=str(row.get("location") or row.get("supplier_name") or "Supplier"),
                    unit_cost=float(row.get("unit_cost") or 0),
                    certificate_type=str(row.get("certificate_type") or "Available upon supplier confirmation"),
                    has_full_trace=bool(row.get("trace_documents") or row.get("certificate_type")),
                )
                for row in catalog
            ]
        return list(db_service.inventory.values())
    records = await create_operational_repositories(session).records.list("inventory")
    return [InventoryItem.model_validate(payload) for payload in records.values()]


def _supplier_response(row: dict[str, Any]) -> Supplier:
    company_name = str(row.get("company_name") or "")
    return Supplier(
        id=str(row["id"]),
        company_name=company_name,
        dba_name=row.get("dba_name"),
        contact_name=str(row.get("contact_name") or company_name),
        contact_title=row.get("contact_title"),
        phone=str(row.get("phone") or ""),
        phone_alt=row.get("phone_alt"),
        email=str(row.get("email") or ""),
        email_quotes=row.get("email_quotes"),
        website=row.get("website"),
        address_line1=str(row.get("address_line1") or ""),
        address_line2=row.get("address_line2"),
        city=str(row.get("city") or ""),
        state_province=str(row.get("state_province") or ""),
        postal_code=str(row.get("postal_code") or ""),
        country=str(row.get("country") or "US"),
        approval_status=str(row.get("approval_status") or "Pending"),
        itar_certified=bool(row.get("itar_certified", False)),
        account_manager=row.get("account_manager"),
        notes=row.get("notes"),
    )

@app.get("/api/suppliers", response_model=List[Supplier])
async def list_suppliers(
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING")),
    session=Depends(get_async_db),
):
    """
    Returns the full supplier directory with contact information.
    """
    if session is None:
        rows = (
            operations_store.list_suppliers()
            if operations_store.storage_engine == "postgresql"
            else supplier_db.list_suppliers()
        )
    else:
        rows = await create_operational_repositories(session).supplier.list_suppliers()
    return [_supplier_response(row) for row in rows]

@app.get("/api/supplier-offers")
async def list_supplier_offers(
    part_number: str = "",
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING", "ROLE_SALES")),
    session=Depends(get_async_db),
):
    if not part_number.strip():
        return []
    normalized_part = part_number.strip().upper()
    if session is None:
        offers = (
            operations_store.get_supplier_offers(normalized_part, quantity_needed=1)
            if operations_store.storage_engine == "postgresql"
            else supplier_db.find_supplier_offers(normalized_part, quantity_needed=1)
        )
    else:
        offers = await create_operational_repositories(session).supplier.offers_for_part(
            normalized_part, quantity_needed=1
        )
    return [
        {
            **offer,
            "id": str(offer.get("id") or offer.get("supplier_part_id") or ""),
            "condition": offer.get("condition") or offer.get("condition_code"),
        }
        for offer in offers
    ]

@app.get("/api/suppliers/{supplier_id}", response_model=Supplier)
async def get_supplier(
    supplier_id: str,
    _user: dict = Depends(require_roles("ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING")),
    session=Depends(get_async_db),
):
    """
    Returns a single supplier's full contact and compliance profile.
    """
    if session is not None:
        profile = await create_operational_repositories(session).supplier.get_profile(supplier_id)
        if profile is None:
            raise HTTPException(status_code=404, detail=f"Supplier '{supplier_id}' not found.")
        return _supplier_response(profile)
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
    messages = []
    for message in fetch_inbox_messages(mailbox):
        attachments = message.get("attachments") or []
        messages.append({
            "mailbox": mailbox,
            "message_id": message.get("message_id", ""),
            "internet_message_id": message.get("internet_message_id"),
            "conversation_id": message.get("conversation_id"),
            "from": message.get("from", ""),
            "subject": message.get("subject", ""),
            "date": message.get("date", ""),
            "body": message.get("body", ""),
            "attachments": [
                {
                    "filename": attachment.get("filename", "attachment"),
                    "content_type": attachment.get("content_type", "application/octet-stream"),
                }
                for attachment in attachments
                if isinstance(attachment, dict)
            ],
        })
    return {"mailbox": mailbox, "messages": messages}

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
