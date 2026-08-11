import json
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.application.job_engine import get_job_engine
from app.api.logging import current_request_id
from app.store import UnitOfWork
from app.store.repositories import ConflictError

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobCreate(BaseModel):
    project_id: str
    unit_id: str | None = None
    job_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("")
def list_jobs(
    request: Request,
    project_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.jobs.list_page(
            project_id=project_id,
            status=status,
            limit=limit,
            cursor=cursor,
        )


@router.post("", status_code=201)
def post_job(data: JobCreate, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(data.project_id)
        payload = dict(data.payload)
        payload.setdefault("_request_id", current_request_id())
        job = uow.jobs.create({**data.model_dump(), "payload": payload})
    get_job_engine(request.app).submit(job["id"])
    return job


@router.get("/stream")
def stream_jobs(request: Request, project_id: str | None = None):
    """任务 SSE：job.progress / job.event / job.done（1s 轮询 diff 推送）。"""
    database = request.app.state.database

    def event_source():
        seen_jobs: dict[str, tuple[float, str]] = {}
        seen_events: set[str] = set()
        sent_done: set[str] = set()
        try:
            while True:
                with UnitOfWork(database) as uow:
                    jobs = uow.jobs.list(project_id=project_id)
                    for job in jobs:
                        progress = float(job["progress"] or 0.0)
                        previous = seen_jobs.get(job["id"])
                        if previous is None or previous[0] != progress or previous[1] != job["status"]:
                            seen_jobs[job["id"]] = (progress, job["status"])
                            payload = {
                                "job_id": job["id"],
                                "progress": progress,
                                "status": job["status"],
                                "parent_job_id": job.get("parent_job_id"),
                            }
                            yield f"event: job.progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                        for event in job.get("events") or []:
                            if event["id"] in seen_events:
                                continue
                            seen_events.add(event["id"])
                            yield f"event: job.event\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                        if job["status"] in ("succeeded", "failed", "canceled") and job["id"] not in sent_done:
                            sent_done.add(job["id"])
                            done = {"job_id": job["id"], "status": job["status"], "result": job.get("result")}
                            yield f"event: job.done\ndata: {json.dumps(done, ensure_ascii=False)}\n\n"
                yield ": keepalive\n\n"
                time.sleep(1)
        except GeneratorExit:
            return

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{job_id}")
def get_job(job_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.jobs.get(job_id)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    engine = get_job_engine(request.app)
    with UnitOfWork(request.app.state.database) as uow:
        result = uow.jobs.request_cancel(job_id)
    engine.cancel(job_id)
    return result


@router.post("/{job_id}/retry")
def retry_job(job_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        job = uow.jobs.get(job_id)
        if job["status"] not in ("failed", "canceled"):
            raise ConflictError("只有失败或已取消的任务可以重试")
        updated = uow.jobs.update_state(job_id, "queued", progress=0.0, error="")
    get_job_engine(request.app).submit(job_id)
    return updated
