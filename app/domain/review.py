from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .enums import ProposalStatus


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PatchOperation(DomainModel):
    op: Literal["add", "replace", "remove"]
    path: str
    value: Any = None


class ChangeProposal(DomainModel):
    id: str
    project_id: str
    unit_id: str | None = None
    artifact_id: str | None = None
    artifact_kind: str
    base_version_id: str | None = None
    title: str
    rationale: str = ""
    operations: list[PatchOperation] = Field(default_factory=list)
    proposed_payload: dict[str, Any] | None = None
    status: ProposalStatus = ProposalStatus.PENDING


class ReviewIssue(DomainModel):
    id: str
    category: str
    severity: str
    message: str
    shot_id: str | None = None
    timecode: float | None = Field(default=None, ge=0.0)
    suggested_operations: list[PatchOperation] = Field(default_factory=list)


class Approval(DomainModel):
    artifact_version_id: str
    approved_by: str = "user"
    note: str = ""
