import json
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.command_context import command_context
from app.api.logging import current_request_id
from app.application.commands import CreateJobCommand, get_command_bus
from app.application.job_engine import get_job_engine
from app.application.jobs.events import list_job_events_after
from app.application.jobs.lifecycle import reset_job_for_retry
from app.store import UnitOfWork

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_JOB_EVENT_ID_PREFIX = "job-event:"


def _job_event_sse_id(event: dict[str, Any]) -> str:
    return (
        f"{_JOB_EVENT_ID_PREFIX}{float(event['created_at'])}:"
        f"{event['id']}"
    )


def _parse_job_event_sse_id(value: str | None) -> tuple[float, str]:
    value = (value or "").strip()
    if not value.startswith(_JOB_EVENT_ID_PREFIX):
        return (0.0, "")
    try:
        timestamp, event_id = value[len(_JOB_EVENT_ID_PREFIX) :].split(":", 1)
        return (float(timestamp), event_id)
    except (TypeError, ValueError):
        return (0.0, "")


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
    payload = dict(data.payload)
    payload.setdefault("_request_id", current_request_id())
    job = get_command_bus(request.app).execute(
        CreateJobCommand(
            project_id=data.project_id,
            unit_id=data.unit_id,
            job_type=data.job_type,
            payload=payload,
        ),
        command_context(request),
    ).result
    get_job_engine(request.app).submit(job["id"])
    return job


@router.get("/stream")
def stream_jobs(request: Request, project_id: str | None = None):
    """任务 SSE：发送进度快照、持久化事件与终态。

    任务列表查询只返回任务摘要，不包含 ``job_events``。事件通过独立的游标查询
    读取，避免此前 ``job.get("events")`` 永远为空而导致前端收不到 ``job.event``。
    """

    database = request.app.state.database
    initial_event_cursor = _parse_job_event_sse_id(
        request.headers.get("last-event-id")
    )

    def event_source():
        seen_jobs: dict[str, tuple[float, str]] = {}
        sent_done: set[str] = set()
        event_cursor = initial_event_cursor
        try:
            while True:
                with UnitOfWork(database) as uow:
                    jobs = uow.jobs.list(project_id=project_id)

                progress_frames: list[dict[str, Any]] = []
                done_frames: list[dict[str, Any]] = []
                for job in jobs:
                    progress = float(job["progress"] or 0.0)
                    previous = seen_jobs.get(job["id"])
                    if (
                        previous is None
                        or previous[0] != progress
                        or previous[1] != job["status"]
                    ):
                        seen_jobs[job["id"]] = (progress, job["status"])
                        progress_frames.append(
                            {
                                "job_id": job["id"],
                                "progress": progress,
                                "status": job["status"],
                                "parent_job_id": job.get("parent_job_id"),
                            }
                        )

                    if (
                        job["status"] in ("succeeded", "failed", "canceled")
                        and job["id"] not in sent_done
                    ):
                        sent_done.add(job["id"])
                        done_frames.append(
                            {
                                "job_id": job["id"],
                                "status": job["status"],
                                "result": job.get("result"),
                            }
                        )

                for payload in progress_frames:
                    yield (
                        "event: job.progress\n"
                        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    )

                events = list_job_events_after(
                    database,
                    project_id=project_id,
                    after_created_at=event_cursor[0],
                    after_id=event_cursor[1],
                )
                for event in events:
                    event_cursor = (float(event["created_at"]), str(event["id"]))
                    yield (
                        f"id: {_job_event_sse_id(event)}\n"
                        "event: job.event\n"
                        f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    )

                for payload in done_frames:
                    yield (
                        "event: job.done\n"
                        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    )

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
    database = request.app.state.database
    reset_job_for_retry(database, job_id)
    get_job_engine(request.app).submit(job_id)
    with UnitOfWork(database) as uow:
        return uow.jobs.get(job_id)
