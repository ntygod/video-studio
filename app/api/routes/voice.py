from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.command_context import command_context
from app.api.logging import current_request_id
from app.application.commands import CreateJobCommand, get_command_bus
from app.application.job_engine import get_job_engine

router = APIRouter(tags=["voice"])


class VoiceLine(BaseModel):
    speaker: str = ""
    text: str
    emotion: str = "neutral"
    pause_after: float = 0.0


class VoiceSynthesisRequest(BaseModel):
    unit_id: str | None = None
    lines: list[VoiceLine] = Field(min_length=1, max_length=500)


@router.post("/api/projects/{project_id}/voice/synthesize")
def synthesize_route(
    project_id: str,
    data: VoiceSynthesisRequest,
    request: Request,
):
    execution = get_command_bus(request.app).execute(
        CreateJobCommand(
            project_id=project_id,
            unit_id=data.unit_id,
            job_type="voice_synthesis",
            payload={
                "lines": [line.model_dump() for line in data.lines],
                "_request_id": current_request_id(),
            },
        ),
        command_context(request),
    )
    job = execution.result
    if job["status"] == "queued":
        get_job_engine(request.app).submit(job["id"])
    return job
