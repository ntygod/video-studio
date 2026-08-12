import hashlib
import json
from dataclasses import replace
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, model_validator

from app.api.command_context import command_context
from app.api.logging import current_request_id
from app.application.commands import (
    CancelRegenerationPlanCommand,
    CreateJobCommand,
    CreateRegenerationPlanCommand,
    RegisterArtifactDerivationCommand,
    SetRegenerationPlanStepInputCommand,
    StartRegenerationPlanCommand,
    get_command_bus,
)
from app.application.freshness_service import (
    list_project_artifact_freshness,
)
from app.application.job_engine import get_job_engine
from app.application.regeneration_plan_service import (
    advance_regeneration_plan,
    regeneration_preview_snapshot_sha256,
)
from app.application.regeneration_preview_service import (
    preview_regeneration_cascade,
)
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


class RegenerationPreviewRequest(BaseModel):
    artifact_ids: list[str] = Field(
        min_length=1,
        max_length=500,
    )
    include_downstream: bool = True


class RegenerationPlanCreateRequest(RegenerationPreviewRequest):
    # A browser creates one token per user intent and reuses it for retries.
    # Omitting it retains the older snapshot-scoped API idempotency behavior.
    client_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )


class RegenerationStepInputRequest(BaseModel):
    replacements: dict[str, str] = Field(
        min_length=1,
        max_length=500,
    )


def _context_with_default_key(request: Request, key: str):
    context = command_context(request)
    if context.idempotency_key:
        return context
    return replace(context, idempotency_key=key)


def _mapping_sha256(value: dict[str, str]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    "/api/projects/{project_id}/artifact-regeneration/preview"
)
def preview_project_regeneration(
    project_id: str,
    data: RegenerationPreviewRequest,
    request: Request,
):
    with UnitOfWork(request.app.state.database) as uow:
        return preview_regeneration_cascade(
            uow,
            project_id,
            data.artifact_ids,
            include_downstream=data.include_downstream,
        )


@router.post(
    "/api/projects/{project_id}/artifact-regeneration/plans",
    status_code=201,
)
def create_regeneration_plan(
    project_id: str,
    data: RegenerationPlanCreateRequest,
    request: Request,
):
    with UnitOfWork(request.app.state.database) as uow:
        preview = preview_regeneration_cascade(
            uow,
            project_id,
            data.artifact_ids,
            include_downstream=data.include_downstream,
        )
    snapshot = regeneration_preview_snapshot_sha256(preview)
    intent = data.client_token or snapshot
    execution = get_command_bus(request.app).execute(
        CreateRegenerationPlanCommand(
            project_id=project_id,
            artifact_ids=data.artifact_ids,
            include_downstream=data.include_downstream,
            expected_snapshot_sha256=snapshot,
        ),
        _context_with_default_key(
            request,
            f"regeneration-plan-create:{project_id}:{intent}",
        ),
    )
    return execution.result


@router.get(
    "/api/projects/{project_id}/artifact-regeneration/plans"
)
def list_regeneration_plans(
    project_id: str,
    request: Request,
    limit: int = 100,
):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        return uow.regeneration_plans.list(
            project_id,
            limit=limit,
        )


@router.get("/api/artifact-regeneration/plans/{plan_id}")
def get_regeneration_plan(plan_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.regeneration_plans.get(plan_id)


@router.post(
    "/api/artifact-regeneration/plans/{plan_id}/start"
)
def start_regeneration_plan(plan_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        plan = uow.regeneration_plans.get(plan_id)
    get_command_bus(request.app).execute(
        StartRegenerationPlanCommand(
            plan_id=plan_id,
            expected_snapshot_sha256=plan["snapshot_sha256"],
        ),
        _context_with_default_key(
            request,
            f"regeneration-plan-start:{plan_id}:"
            f"{plan['snapshot_sha256']}",
        ),
    )
    return advance_regeneration_plan(
        request.app.state.database,
        plan_id,
        get_job_engine(request.app),
    )


@router.post(
    "/api/artifact-regeneration/steps/{step_id}/input"
)
def set_regeneration_step_input(
    step_id: str,
    data: RegenerationStepInputRequest,
    request: Request,
):
    execution = get_command_bus(request.app).execute(
        SetRegenerationPlanStepInputCommand(
            step_id=step_id,
            replacements=data.replacements,
        ),
        _context_with_default_key(
            request,
            f"regeneration-step-input:{step_id}:"
            f"{_mapping_sha256(data.replacements)}",
        ),
    )
    step = execution.result
    with UnitOfWork(request.app.state.database) as uow:
        plan = uow.regeneration_plans.get(step["plan_id"])
    if plan["status"] == "running":
        return advance_regeneration_plan(
            request.app.state.database,
            plan["id"],
            get_job_engine(request.app),
        )
    return plan


@router.post(
    "/api/artifact-regeneration/plans/{plan_id}/cancel"
)
def cancel_regeneration_plan(plan_id: str, request: Request):
    execution = get_command_bus(request.app).execute(
        CancelRegenerationPlanCommand(plan_id=plan_id),
        _context_with_default_key(
            request,
            f"regeneration-plan-cancel:{plan_id}",
        ),
    )
    plan = execution.result
    engine = getattr(request.app.state, "job_engine", None)
    if engine is not None:
        for step in plan.get("steps") or []:
            if step.get("job_id"):
                engine.cancel(step["job_id"])
    return plan


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
