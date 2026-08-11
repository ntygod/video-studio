from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.application.job_engine import get_job_engine
from app.application.timeline_service import compile_timeline
from app.api.logging import current_request_id
from app.store import UnitOfWork

router = APIRouter(tags=["timeline"])


class CompileRequest(BaseModel):
    unit_id: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class RenderRequest(BaseModel):
    timeline: dict[str, Any]
    name: str = "成片"


@router.post("/api/projects/{project_id}/timeline/compile")
def compile_route(project_id: str, data: CompileRequest, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        timeline = compile_timeline(uow, project_id, data.unit_id, data.parameters)
        artifact = uow.artifacts.find_latest(project_id, data.unit_id, "timeline")
        if artifact:
            uow.artifacts.add_version(
                artifact["id"],
                timeline,
                source="system",
                note="重新编译时间线",
            )
            artifact = uow.artifacts.get(artifact["id"])
        else:
            artifact = uow.artifacts.create(
                project_id=project_id,
                unit_id=data.unit_id,
                kind="timeline",
                name="时间线",
                schema_id="open/timeline@1",
                payload=timeline,
                source="system",
            )
        return {"timeline": timeline, "artifact": artifact}


@router.post("/api/projects/{project_id}/timeline/render", status_code=201)
def render_route(project_id: str, data: RenderRequest, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        job = uow.jobs.create(
            {
                "project_id": project_id,
                "unit_id": None,
                "job_type": "render",
                "payload": {
                    "timeline": data.timeline,
                    "name": data.name,
                    "_request_id": current_request_id(),
                },
            }
        )
    get_job_engine(request.app).submit(job["id"])
    return job
