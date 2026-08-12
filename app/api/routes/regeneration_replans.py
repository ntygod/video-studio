"""Replan endpoints kept separate from execution endpoints."""

from dataclasses import replace
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.command_context import command_context
from app.application.commands import (
    ReplanRegenerationPlanCommand,
    get_command_bus,
)
from app.application.regeneration_plan_service import (
    regeneration_preview_snapshot_sha256,
)
from app.application.regeneration_preview_service import (
    preview_regeneration_cascade,
)
from app.application.regeneration_replan_service import (
    get_regeneration_plan_lineage,
)
from app.store import UnitOfWork

router = APIRouter(tags=["artifact-dependencies"])

ReplanSourceStatus = Literal[
    "draft",
    "blocked",
    "failed",
    "canceled",
]


class RegenerationPlanReplanRequest(BaseModel):
    expected_source_status: ReplanSourceStatus
    expected_execution_attempt: int = Field(ge=0, le=20)
    reason: str = Field(default="", max_length=2000)
    client_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )


def _context_with_default_key(request: Request, key: str):
    context = command_context(request)
    if context.idempotency_key:
        return context
    return replace(context, idempotency_key=key)


@router.get(
    "/api/artifact-regeneration/plans/{plan_id}/lineage"
)
def get_regeneration_lineage(plan_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return get_regeneration_plan_lineage(uow, plan_id)


@router.post(
    "/api/artifact-regeneration/plans/{plan_id}/replan",
    status_code=201,
)
def replan_regeneration_plan(
    plan_id: str,
    data: RegenerationPlanReplanRequest,
    request: Request,
):
    # Keep validation inside CommandBus so a repeated client token can replay
    # the original successful Operation before the source's lineage changes.
    with UnitOfWork(request.app.state.database) as uow:
        source = uow.regeneration_plans.get(plan_id)
        preview = preview_regeneration_cascade(
            uow,
            source["project_id"],
            list(source["root_artifact_ids"]),
            include_downstream=bool(source["include_downstream"]),
        )
    snapshot = regeneration_preview_snapshot_sha256(preview)
    intent = data.client_token or snapshot
    execution = get_command_bus(request.app).execute(
        ReplanRegenerationPlanCommand(
            source_plan_id=plan_id,
            expected_source_status=data.expected_source_status,
            expected_execution_attempt=(
                data.expected_execution_attempt
            ),
            expected_snapshot_sha256=snapshot,
            reason=data.reason,
        ),
        _context_with_default_key(
            request,
            f"regeneration-plan-replan:{plan_id}:{intent}",
        ),
    )
    return execution.result
