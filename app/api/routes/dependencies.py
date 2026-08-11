from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.command_context import command_context
from app.application.commands import (
    RegisterArtifactDerivationCommand,
    get_command_bus,
)
from app.store import UnitOfWork

router = APIRouter(tags=["artifact-dependencies"])


class DerivationCreate(BaseModel):
    input_version_ids: list[str] = Field(
        min_length=1,
        max_length=500,
    )
    dependency_type: str = "derived_from"
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


@router.post(
    "/api/artifact-versions/{version_id}/derivation",
    status_code=201,
)
def register_derivation(
    version_id: str,
    data: DerivationCreate,
    request: Request,
):
    return get_command_bus(request.app).execute(
        RegisterArtifactDerivationCommand(
            output_version_id=version_id,
            input_version_ids=data.input_version_ids,
            dependency_type=data.dependency_type,
            metadata=data.metadata,
            provenance=data.provenance,
        ),
        command_context(request),
    ).result


@router.get("/api/artifact-versions/{version_id}/provenance")
def get_provenance(version_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return {
            "artifact_version_id": version_id,
            "provenance": uow.artifact_graph.provenance(
                version_id
            ),
        }


@router.get("/api/artifacts/{artifact_id}/freshness")
def get_freshness(artifact_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.artifact_graph.get_freshness(artifact_id)


@router.get("/api/artifacts/{artifact_id}/dependencies")
def get_dependencies(artifact_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.artifact_graph.dependencies_for_artifact(
            artifact_id
        )


@router.get("/api/artifacts/{artifact_id}/impact")
def get_impact(artifact_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.artifact_graph.impact(artifact_id)
