from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from models.db_models import RFQ, RFQItem, Quote, QuoteItem, AgentAuditLog, Supplier
from services.db_service import db_service
from services.orchestration_service import orchestration_service

app = FastAPI(
    title="Winged Tycoons RFQ-to-Quote Multi-Agent API",
    description="Automated multi-agent processing pipeline with Human-in-the-Loop approval gates.",
    version="1.0.0"
)

# API Schemas
class IntakeRequest(BaseModel):
    raw_text: str = Field(..., description="Raw email or RFQ text submitted by customer")

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

# Endpoints

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
async def submit_rfq(request: IntakeRequest):
    """
    Submits raw unstructured text representing a customer RFQ.
    Triggers parsing and initial pipeline validation.
    """
    if not request.raw_text.strip():
        raise HTTPException(status_code=400, detail="Raw RFQ text cannot be empty.")
        
    # Standard mock customer resolution (simulating a database record lookup)
    customer_name = "Delta MRO Services"
    customer_email = "procurement@deltamro.com"
    if "united" in request.raw_text.lower():
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
async def trigger_process(rfq_id: str):
    """
    Manually advances the state-machine of the RFQ pipeline.
    """
    rfq = db_service.get_rfq(rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found.")
        
    res = await orchestration_service.process_rfq_pipeline(rfq_id)
    return res

@app.get("/api/rfqs", response_model=List[RFQ])
async def list_rfqs():
    """
    Retrieves all RFQs.
    """
    return db_service.list_rfqs()

@app.get("/api/rfqs/{rfq_id}")
async def get_rfq_detail(rfq_id: str):
    """
    Retrieves complete status details, items, audit logs, and associated quotes.
    """
    rfq = db_service.get_rfq(rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found.")
        
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
async def approve_quote(quote_id: str, request: ApproveRequest):
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
async def reject_quote(quote_id: str, request: RejectRequest):
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

@app.get("/api/inventory")
async def get_inventory():
    """
    Fetch mock internal stock inventory.
    """
    return list(db_service.inventory.values())

@app.get("/api/suppliers", response_model=List[Supplier])
async def list_suppliers():
    """
    Returns the full supplier directory with contact information.
    """
    return list(db_service.suppliers.values())

@app.get("/api/suppliers/{supplier_id}", response_model=Supplier)
async def get_supplier(supplier_id: str):
    """
    Returns a single supplier's full contact and compliance profile.
    """
    supplier = db_service.suppliers.get(supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail=f"Supplier '{supplier_id}' not found.")
    return supplier
