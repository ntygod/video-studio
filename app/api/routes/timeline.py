from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.command_context import command_context
from app.api.logging import current_request_id
from app.application.commands import (
    CompileTimelineCommand,
    CreateJobCommand,
    get_command_bus,
)
from app.application.job_engine import get_job_engine

router = APIRouter(tags=["timeline"])


class CompileRequest(BaseModel):
    unit_id: str | None = None
    input_version_ids: list[str] = Field(
        default_factory=list,
        max_length=500,
    )
    parameters: dict[str, Any] = Field(default_factory=dict)


class RenderRequest(BaseModel):
    timeline: dict[str, Any]
    name: str = "成片"


@router.post("/api/projects/{project_id}/timeline/compile")
def compile_route(
    project_id: str,
    data: CompileRequest,
    request: Request,
):
    return get_command_bus(request.app).execute(
        CompileTimelineCommand(
            project_id=project_id,
            unit_id=data.unit_id,
            parameters=data.parameters,
            input_version_ids=data.input_version_ids,
        ),
        command_context(request),
    ).result


@router.post(
    "/api/projects/{project_id}/timeline/render",
    status_code=201,
)
def render_route(
    project_id: str,
    data: RenderRequest,
    request: Request,
):
    execution = get_command_bus(request.app).execute(
        CreateJobCommand(
            project_id=project_id,
            unit_id=None,
            job_type="render",
            payload={
                "timeline": data.timeline,
                "name": data.name,
                "_request_id": current_request_id(),
            },
        ),
        command_context(request),
    )
    job = execution.result
    if job["status"] == "queued":
        get_job_engine(request.app).submit(job["id"])
    return job
