from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.application.job_engine import get_job_engine
from app.store import UnitOfWork

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobCreate(BaseModel):
    project_id: str
    unit_id: str | None = None
    job_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("")
def list_jobs(request: Request, project_id: str | None = None):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.jobs.list(project_id=project_id)


@router.post("", status_code=201)
def post_job(data: JobCreate, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(data.project_id)
        job = uow.jobs.create(data.model_dump())
    get_job_engine(request.app).submit(job["id"])
    return job


@router.get("/{job_id}")
def get_job(job_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.jobs.get(job_id)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.jobs.request_cancel(job_id)


@router.post("/{job_id}/retry")
def retry_job(job_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        job = uow.jobs.get(job_id)
        if job["status"] not in ("failed", "canceled"):
            raise RuntimeError("只有失败或已取消的任务可以重试")
        updated = uow.jobs.update_state(job_id, "queued", progress=0.0, error="")
    get_job_engine(request.app).submit(job_id)
    return updated
