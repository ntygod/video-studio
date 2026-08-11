from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.domain.enums import ArtifactStatus
from app.store import UnitOfWork
from app.store.repositories import ConflictError

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
def list_artifacts(
    project_id: str,
    request: Request,
    unit_id: str | None = None,
    kind: str | None = None,
    include_payload: bool = False,
    limit: int = 50,
    cursor: str | None = None,
):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        return uow.artifacts.list_page(
            project_id,
            unit_id=unit_id,
            kind=kind,
            include_payload=include_payload,
            limit=limit,
            cursor=cursor,
        )


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


def _dispatch_unit_summary(unit_id: str | None, request: Request) -> None:
    if not unit_id:
        return
    from app.application.agent.compaction import ensure_unit_summary
    from app.application.job_engine import get_job_engine

    ensure_unit_summary(
        request.app.state.database,
        get_job_engine(request.app),
        unit_id,
    )


@router.get("/api/artifact-versions/{version_a}/diff/{version_b}")
def diff_versions(version_a: str, version_b: str, request: Request):
    """结构化版本 diff（T4.3）：按字段路径对齐，不是文本 diff。"""
    from app.application.artifacts import _diff_payloads

    with UnitOfWork(request.app.state.database) as uow:
        left = uow.artifacts.get_version(version_a)
        right = uow.artifacts.get_version(version_b)
        return {
            "version_a": {"id": left["id"], "version": left["version"]},
            "version_b": {"id": right["id"], "version": right["version"]},
            "field_diffs": _diff_payloads(left["payload"], right["payload"]),
        }


@router.post("/api/artifacts/{artifact_id}/restore/{version_id}", status_code=201)
def restore_version(artifact_id: str, version_id: str, request: Request):
    """回滚到目标版本内容，追加新版本而非覆盖历史（T4.3）。"""
    from app.store.repositories import NotFoundError

    with UnitOfWork(request.app.state.database) as uow:
        target = uow.artifacts.get_version(version_id)
        if target["artifact_id"] != artifact_id:
            raise NotFoundError(version_id)
        artifact = uow.artifacts.get(artifact_id)
        current = artifact.get("current_version") or {}
        if current.get("status") == "locked":
            raise ConflictError("artifact is locked")
        return uow.artifacts.add_version(
            artifact_id,
            target["payload"],
            source="user",
            note=f"回滚到 v{target['version']}",
            parent_version_id=current.get("id"),
        )


@router.post("/api/artifact-versions/{version_id}/approve")
def approve_version(version_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        result = uow.artifacts.set_status(version_id, ArtifactStatus.APPROVED.value)
        unit_id = uow.artifacts.get(result["artifact_id"])["unit_id"]
    _dispatch_unit_summary(unit_id, request)
    return result


@router.post("/api/artifact-versions/{version_id}/lock")
def lock_version(version_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        result = uow.artifacts.set_status(version_id, ArtifactStatus.LOCKED.value)
        unit_id = uow.artifacts.get(result["artifact_id"])["unit_id"]
    _dispatch_unit_summary(unit_id, request)
    return result

