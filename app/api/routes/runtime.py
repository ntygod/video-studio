"""Observability and reconciliation API for the durable task runtime."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.store import UnitOfWork

router = APIRouter(tags=["task-runtime"])


class ProviderRequestResolve(BaseModel):
    resolution: Literal[
        "not_sent",
        "completed_external",
        "failed_external",
        "duplicate_risk_accepted",
    ]
    note: str = Field(default="", max_length=8000)
    provider_request_id: str = Field(default="", max_length=300)


@router.get("/api/projects/{project_id}/runtime-plans")
def list_runtime_plans(
    project_id: str,
    request: Request,
    kind: str | None = None,
    status: str | None = None,
    limit: int = 100,
):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        return uow.task_runtime.list_plans(
            project_id,
            kind=kind,
            status=status,
            limit=limit,
        )


@router.get("/api/runtime-plans/{plan_id}")
def get_runtime_plan(plan_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.task_runtime.get_plan(plan_id)


@router.get("/api/runtime-tasks/{task_id}")
def get_runtime_task(task_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.task_runtime.get_task(task_id)


@router.get("/api/runtime-plans/{plan_id}/events")
def list_runtime_plan_events(
    plan_id: str,
    request: Request,
    after_seq: int = 0,
    limit: int = 500,
):
    with UnitOfWork(request.app.state.database) as uow:
        events = uow.task_runtime.list_events(
            plan_id,
            after_seq=max(0, int(after_seq)),
            limit=limit,
        )
    return {
        "items": events,
        "next_after_seq": events[-1]["seq"] if events else after_seq,
    }


@router.get("/api/runtime-plans/{plan_id}/provider-requests")
def list_runtime_provider_requests(
    plan_id: str,
    request: Request,
    status: str | None = None,
    limit: int = 100,
):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.task_runtime.list_provider_requests(
            plan_id,
            status=status,
            limit=limit,
        )


@router.get("/api/runtime-provider-requests/{request_id}")
def get_runtime_provider_request(request_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.task_runtime.get_provider_request(request_id)


@router.post("/api/runtime-provider-requests/{request_id}/resolve")
def resolve_runtime_provider_request(
    request_id: str,
    data: ProviderRequestResolve,
    request: Request,
):
    actor_id = str(
        getattr(request.state, "actor_id", "") or "workspace-user"
    )
    with UnitOfWork(request.app.state.database) as uow:
        return uow.task_runtime.resolve_provider_request(
            request_id,
            resolution=data.resolution,
            note=data.note,
            provider_request_id=data.provider_request_id,
            resolved_by_type="user",
            resolved_by_id=actor_id,
        )
