from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import JobStatus


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JobEvent(DomainModel):
    id: str
    job_id: str
    level: str = "info"
    stage: str = ""
    message: str
    progress: float | None = Field(default=None, ge=0.0, le=100.0)
    created_at: float


class NodeRun(DomainModel):
    id: str
    job_id: str
    node_key: str
    status: JobStatus = JobStatus.QUEUED
    input_hash: str = ""
    output_refs: list[str] = Field(default_factory=list)
    error: str = ""


class PersistentJob(DomainModel):
    id: str
    project_id: str
    unit_id: str | None = None
    job_type: str
    status: JobStatus = JobStatus.QUEUED
    progress: float = Field(default=0.0, ge=0.0, le=100.0)
    cancel_requested: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str = ""
