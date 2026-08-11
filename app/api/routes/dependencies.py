from dataclasses import replace
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, model_validator

from app.api.command_context import command_context
from app.api.logging import current_request_id
from app.application.commands import (
    CreateJobCommand,
    RegisterArtifactDerivationCommand,
    get_command_bus,
)
from app.application.freshness_service import (
    list_project_artifact_freshness,
)
from app.application.job_engine import get_job_engine
from app.application.regeneration_service import (
    prepare_artifact_regeneration,
)
from app.store import UnitOfWork

router = APIRouter(tags=["artifact-dependencies"])


class DerivationCreate(BaseModel):
    input_version_ids: list[str] = Field(
        default_factory=list,
        max_length=500,
    )
    input_asset_ids: list[str] = Field(
        default_factory=list,
        max_length=500,
    )
    dependency_type: str = "derived_from"
    asset_dependency_type: str = "uses_asset"
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_inputs(self):
        if not self.input_version_ids and not self.input_asset_ids:
            raise ValueError(
                "derivation requires ArtifactVersion or Asset inputs"
            )
        return self


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
            input_asset_ids=data.input_asset_ids,
            dependency_type=data.dependency_type,
            asset_dependency_type=data.asset_dependency_type,
            metadata=data.metadata,
            provenance=data.provenance,
        ),
        command_context(request),
    ).result


@router.get(
    "/api/projects/{project_id}/artifact-freshness"
)
def get_project_freshness(
    project_id: str,
    request: Request,
    include_fresh: bool = False,
):
    with UnitOfWork(request.app.state.database) as uow:
        return list_project_artifact_freshness(
            uow,
            project_id,
            include_fresh=include_fresh,
        )


@router.post(
    "/api/artifacts/{artifact_id}/regenerate",
    status_code=201,
)
def regenerate_artifact(
    artifact_id: str,
    request: Request,
):
    with UnitOfWork(request.app.state.database) as uow:
        specification = prepare_artifact_regeneration(
            uow,
            artifact_id,
        )

    context = command_context(request)
    if not context.idempotency_key:
        context = replace(
            context,
            idempotency_key=(
                "artifact-regenerate:"
                f"{artifact_id}:"
                f"{specification['expected_target_version_id']}"
            ),
        )
    payload = {
        **specification["payload"],
        "_request_id": current_request_id(),
    }
    job = get_command_bus(request.app).execute(
        CreateJobCommand(
            project_id=specification["project_id"],
            unit_id=specification["unit_id"],
            job_type="generate",
            payload=payload,
        ),
        context,
    ).result
    if job["status"] == "queued":
        get_job_engine(request.app).submit(job["id"])
    return job


@router.get("/api/artifact-versions/{version_id}/provenance")
def get_provenance(version_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return {
            "artifact_version_id": version_id,
            "provenance": uow.artifact_graph.provenance(
                version_id
            ),
            "asset_dependencies": (
                uow.artifact_graph.asset_dependencies_for_version(
                    version_id
                )
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


@router.get(
    "/api/artifacts/{artifact_id}/asset-dependencies"
)
def get_asset_dependencies(
    artifact_id: str,
    request: Request,
):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.artifact_graph.asset_dependencies_for_artifact(
            artifact_id
        )


@router.get("/api/assets/{asset_id}/dependents")
def get_asset_dependents(asset_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.artifact_graph.dependents_for_asset(asset_id)


@router.get("/api/artifacts/{artifact_id}/impact")
def get_impact(artifact_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.artifact_graph.impact(artifact_id)
