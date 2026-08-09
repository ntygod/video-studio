from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.application.job_engine import get_job_engine
from app.store import UnitOfWork

router = APIRouter(tags=["generate"])


class GenerateRequest(BaseModel):
    capability: str = "llm"
    prompt: str = ""
    schema_id: str = "freeform"
    artifact_kind: str = "generated"
    artifact_name: str = "AI 生成"
    context: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)


@router.post("/api/projects/{project_id}/generate", status_code=201)
def generate(project_id: str, data: GenerateRequest, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        job = uow.jobs.create(
            {
                "project_id": project_id,
                "unit_id": None,
                "job_type": "generate",
                "payload": {
                    **data.model_dump(),
                    "context": data.context,
                    "parameters": data.parameters,
                },
            }
        )
    get_job_engine(request.app).submit(job["id"])
    return job
