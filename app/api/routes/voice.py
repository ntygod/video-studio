from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.application.job_engine import get_job_engine
from app.application.voice_service import synthesize_lines
from app.store import UnitOfWork

router = APIRouter(tags=["voice"])


class VoiceLine(BaseModel):
    speaker: str = ""
    text: str
    emotion: str = "neutral"
    pause_after: float = 0.0


class VoiceSynthesisRequest(BaseModel):
    unit_id: str | None = None
    lines: list[VoiceLine]


@router.post("/api/projects/{project_id}/voice/synthesize")
def synthesize_route(project_id: str, data: VoiceSynthesisRequest, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        job = uow.jobs.create(
            {
                "project_id": project_id,
                "unit_id": data.unit_id,
                "job_type": "voice_synthesis",
                "payload": {"lines": [line.model_dump() for line in data.lines]},
            }
        )
    get_job_engine(request.app).submit(job["id"])
    return job
