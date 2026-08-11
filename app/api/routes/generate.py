from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.application.job_engine import get_job_engine
from app.api.logging import current_request_id
from app.store import UnitOfWork

router = APIRouter(tags=["generate"])


class GenerateRequest(BaseModel):
    unit_id: str | None = None
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
                "unit_id": data.unit_id,
                "job_type": "generate",
                "payload": {
                    **data.model_dump(),
                    "context": data.context,
                    "parameters": data.parameters,
                    "_request_id": current_request_id(),
                },
            }
        )
    get_job_engine(request.app).submit(job["id"])
    return job


class BatchGenerateRequest(BaseModel):
    unit_ids: list[str]
    capability: str = "image"
    prompt_template: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


def _render_prompt(template: str, unit: dict[str, Any], style_direction: str) -> str:
    mapping = {
        "{unit.title}": unit.get("title", ""),
        "{unit.summary}": unit.get("summary", ""),
        "{bible.style.visual_direction}": style_direction,
    }
    result = template
    for key, value in mapping.items():
        result = result.replace(key, value)
    return result


@router.post("/api/projects/{project_id}/generate/batch", status_code=201)
def generate_batch(project_id: str, data: BatchGenerateRequest, request: Request):
    engine = get_job_engine(request.app)
    with UnitOfWork(request.app.state.database) as uow:
        project = uow.projects.get(project_id)
        style_direction = project.bible.style.visual_direction
        units = {unit.id: unit for unit in uow.units.list(project_id)}
        missing = [unit_id for unit_id in data.unit_ids if unit_id not in units]
        if missing:
            from app.store.repositories import NotFoundError

            raise NotFoundError(missing[0])
        parent = uow.jobs.create(
            {
                "project_id": project_id,
                "unit_id": None,
                "job_type": "batch",
                "payload": {"_request_id": current_request_id()},
            }
        )
        child_ids: list[str] = []
        for unit_id in data.unit_ids:
            unit = units[unit_id]
            prompt = _render_prompt(
                data.prompt_template,
                unit.model_dump(mode="json"),
                style_direction,
            )
            child = uow.jobs.create(
                {
                    "project_id": project_id,
                    "unit_id": unit_id,
                    "job_type": "media",
                    "parent_job_id": parent["id"],
                    "payload": {
                        "capability": data.capability,
                        "prompt": prompt,
                        "parameters": data.params,
                        "name": unit.title,
                        "_request_id": current_request_id(),
                    },
                }
            )
            child_ids.append(child["id"])
        uow.jobs.update_payload(
            parent["id"],
            {"child_job_ids": child_ids, "child_count": len(child_ids)},
        )
    for child_id in child_ids:
        engine.submit(child_id)
    engine.submit(parent["id"])
    return {"parent_job_id": parent["id"], "child_job_ids": child_ids}
