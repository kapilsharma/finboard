import uuid

from fastapi import APIRouter, status

from finboard.api.deps import JobServiceDep
from finboard.api.schemas import JobList, JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(service: JobServiceDep) -> JobList:
    return JobList(items=[JobOut.model_validate(j) for j in await service.list_recent()])


@router.get("/{job_id}")
async def get_job(job_id: uuid.UUID, service: JobServiceDep) -> JobOut:
    return JobOut.model_validate(await service.get(job_id))


@router.post("/ping", status_code=status.HTTP_202_ACCEPTED)
async def ping_worker(service: JobServiceDep) -> JobOut:
    """Queue a no-op job to check the worker pipeline end to end; poll GET /jobs/{id}."""
    return JobOut.model_validate(await service.submit("maintenance.ping"))
