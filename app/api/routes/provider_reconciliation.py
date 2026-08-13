"""Turn-scoped Provider request observability."""

from fastapi import APIRouter, Request

from app.application.agent.durable_loop import AGENT_PLAN_KIND
from app.store import UnitOfWork
from app.store.repositories import NotFoundError

router = APIRouter(tags=["task-runtime"])


@router.get("/api/turns/{turn_id}/provider-requests")
def list_turn_provider_requests(
    turn_id: str,
    request: Request,
    status: str | None = None,
    limit: int = 100,
):
    with UnitOfWork(request.app.state.database) as uow:
        uow.agent_turns.get(turn_id)
        plan = uow.task_runtime.find_plan_by_subject(
            "agent_turn",
            turn_id,
            kind=AGENT_PLAN_KIND,
        )
        if plan is None:
            raise NotFoundError(turn_id)
        return uow.task_runtime.list_provider_requests(
            plan["id"],
            status=status,
            limit=limit,
        )


__all__ = ["router"]
