from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.command_context import command_context
from app.api.logging import current_request_id
from app.application.commands import (
    CreateBatchJobsCommand,
    CreateJobCommand,
    get_command_bus,
)
from app.application.job_engine import get_job_engine
from app.store import UnitOfWork

router = APIRouter(tags=["generate"])


class GenerateRequest(BaseModel):
    unit_id: str | None = None
    capability: str = "llm"
    prompt: str = ""
    prompt_version: str = "inline@1"
    schema_id: str = "freeform"
    artifact_kind: str = "generated"
    artifact_name: str = "AI 生成"
    input_version_ids: list[str] = Field(
        default_factory=list,
        max_length=500,
    )
    input_asset_ids: list[str] = Field(
        default_factory=list,
        max_length=500,
    )
    context: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)


@router.post("/api/projects/{project_id}/generate", status_code=201)
def generate(
    project_id: str,
    data: GenerateRequest,
    request: Request,
):
    execution = get_command_bus(request.app).execute(
        CreateJobCommand(
            project_id=project_id,
            unit_id=data.unit_id,
            job_type="generate",
            payload={
                **data.model_dump(),
                "context": data.context,
                "parameters": data.parameters,
                "_request_id": current_request_id(),
            },
        ),
        command_context(request),
    )
    job = execution.result
    if job["status"] == "queued":
        get_job_engine(request.app).submit(job["id"])
    return job


class BatchGenerateRequest(BaseModel):
    unit_ids: list[str] = Field(
        min_length=1,
        max_length=500,
    )
    capability: str = "image"
    prompt_template: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


@router.post(
    "/api/projects/{project_id}/generate/batch",
    status_code=201,
)
def generate_batch(
    project_id: str,
    data: BatchGenerateRequest,
    request: Request,
):
    execution = get_command_bus(request.app).execute(
        CreateBatchJobsCommand(
            project_id=project_id,
            unit_ids=data.unit_ids,
            capability=data.capability,
            prompt_template=data.prompt_template,
            params=data.params,
            request_id=current_request_id(),
        ),
        command_context(request),
    )
    result = execution.result
    engine = get_job_engine(request.app)
    job_ids = [
        *result["child_job_ids"],
        result["parent_job_id"],
    ]
    with UnitOfWork(request.app.state.database) as uow:
        queued = [
            job_id
            for job_id in job_ids
            if uow.jobs.get(job_id)["status"] == "queued"
        ]
    for job_id in queued:
        engine.submit(job_id)
    return result
