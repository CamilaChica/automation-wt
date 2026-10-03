from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_roles
from services import partsbase_service

router = APIRouter()

PARTSBASE_ROLES = ("ROLE_INTERNAL", "ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PURCHASING", "ROLE_SALES")


class PartsBaseQuoteRequest(BaseModel):
    part_numbers: list[str] | str


@router.post("/api/internal/rfqs/{rfq_id}/partsbase-quote", status_code=202)
async def request_partsbase_quote(
    rfq_id: str,
    request: PartsBaseQuoteRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_roles(*PARTSBASE_ROLES)),
):
    try:
        parts = partsbase_service.normalize_part_numbers(request.part_numbers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not partsbase_service.credentials_configured():
        raise HTTPException(status_code=503, detail="PartsBase login is not configured on the server.")
    job = partsbase_service.start_job(rfq_id, parts, user.get("email", ""))
    background_tasks.add_task(partsbase_service.run_job, job["job_id"])
    return job


@router.get("/api/internal/partsbase-jobs/{job_id}")
async def get_partsbase_job(job_id: str, user: dict = Depends(require_roles(*PARTSBASE_ROLES))):
    job = partsbase_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="PartsBase request not found.")
    return job
