"""Runtime policy decisions, approvals, and budget observability."""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.application.agent.durable_executor import (
    get_durable_agent_turn_executor,
)
from app.application.agent.durable_loop import AGENT_PLAN_KIND
from app.application.job_engine import get_job_engine
from app.store import UnitOfWork
from app.store.repositories import NotFoundError

router = APIRouter(tags=["runtime-policy"])


class PolicyDecisionResolve(BaseModel):
    note: str = Field(default="", max_length=2000)


def _turn_plan(uow: UnitOfWork, turn_id: str) -> dict[str, Any]:
    uow.agent_turns.get(turn_id)
    plan = uow.task_runtime.find_plan_by_subject(
        "agent_turn",
        turn_id,
        kind=AGENT_PLAN_KIND,
    )
    if plan is None:
        raise NotFoundError(turn_id)
    return plan


def _publish_resolution(
    request: Request,
    plan: dict[str, Any],
    event: dict[str, Any] | None,
) -> None:
    if plan["kind"] != AGENT_PLAN_KIND:
        return
    executor = get_durable_agent_turn_executor(
        request.app,
        get_job_engine(request.app),
    )
    if event is None:
        executor.notify()
        return
    from app.api.routes.conversations import _publish, _runtime_event

    turn_id = str(plan.get("subject_id") or "")
    if turn_id:
        _publish(turn_id, _runtime_event(turn_id, event))
    executor.notify()


@router.get("/api/turns/{turn_id}/policy-decisions")
def list_turn_policy_decisions(
    turn_id: str,
    request: Request,
    status: str | None = None,
):
    with UnitOfWork(request.app.state.database) as uow:
        plan = _turn_plan(uow, turn_id)
        return uow.task_runtime.list_policy_decisions(
            plan["id"],
            status=status,
        )


@router.get("/api/projects/{project_id}/runtime-policy-decisions")
def list_project_policy_decisions(
    project_id: str,
    request: Request,
    status: str | None = None,
    kind: str | None = None,
    limit: int = 100,
):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        return uow.task_runtime.list_project_policy_decisions(
            project_id,
            status=status,
            kind=kind,
            limit=limit,
        )


@router.get("/api/runtime-policy-decisions/{decision_id}")
def get_runtime_policy_decision(decision_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.task_runtime.get_policy_decision(decision_id)


@router.get("/api/runtime-plans/{plan_id}/budget")
def get_runtime_budget(plan_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.task_runtime.budget_state(plan_id)


def _resolve(
    decision_id: str,
    data: PolicyDecisionResolve,
    request: Request,
    *,
    approved: bool,
):
    actor_id = str(
        getattr(request.state, "actor_id", "") or "workspace-user"
    )
    with UnitOfWork(request.app.state.database) as uow:
        result = uow.task_runtime.resolve_policy_decision(
            decision_id,
            approved=approved,
            decided_by_type="user",
            decided_by_id=actor_id,
            note=data.note,
        )
    _publish_resolution(request, result["plan"], result.get("event"))
    return result["decision"]


@router.post("/api/runtime-policy-decisions/{decision_id}/approve")
def approve_runtime_policy_decision(
    decision_id: str,
    data: PolicyDecisionResolve,
    request: Request,
):
    return _resolve(decision_id, data, request, approved=True)


@router.post("/api/runtime-policy-decisions/{decision_id}/deny")
def deny_runtime_policy_decision(
    decision_id: str,
    data: PolicyDecisionResolve,
    request: Request,
):
    return _resolve(decision_id, data, request, approved=False)
