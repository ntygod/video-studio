from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.domain.enums import ArtifactStatus
from app.store import UnitOfWork

router = APIRouter(tags=["artifacts"])


class ArtifactCreate(BaseModel):
    unit_id: str | None = None
    kind: str
    name: str
    schema_id: str = "freeform"
    payload: dict[str, Any] = Field(default_factory=dict)


class ArtifactVersionCreate(BaseModel):
    payload: dict[str, Any]
    note: str = ""


@router.get("/api/projects/{project_id}/artifacts")
def list_artifacts(project_id: str, request: Request, unit_id: str | None = None):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        return uow.artifacts.list(project_id, unit_id=unit_id)


@router.post("/api/projects/{project_id}/artifacts", status_code=201)
def post_artifact(project_id: str, data: ArtifactCreate, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        return uow.artifacts.create(
            project_id=project_id,
            unit_id=data.unit_id,
            kind=data.kind,
            name=data.name,
            schema_id=data.schema_id,
            payload=data.payload,
        )


@router.get("/api/artifacts/{artifact_id}")
def get_artifact(artifact_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.artifacts.get(artifact_id)


@router.get("/api/artifacts/{artifact_id}/versions")
def list_versions(artifact_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        uow.artifacts.get(artifact_id)
        return uow.artifacts.versions(artifact_id)


@router.post("/api/artifacts/{artifact_id}/versions", status_code=201)
def post_version(artifact_id: str, data: ArtifactVersionCreate, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.artifacts.add_version(
            artifact_id,
            data.payload,
            source="user",
            note=data.note,
        )


@router.post("/api/artifact-versions/{version_id}/approve")
def approve_version(version_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.artifacts.set_status(version_id, ArtifactStatus.APPROVED.value)


@router.post("/api/artifact-versions/{version_id}/lock")
def lock_version(version_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.artifacts.set_status(version_id, ArtifactStatus.LOCKED.value)

