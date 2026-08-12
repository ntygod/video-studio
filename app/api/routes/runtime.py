"""Read-only observability API for the durable task runtime."""

from fastapi import APIRouter, Request

from app.store import UnitOfWork

router = APIRouter(tags=["task-runtime"])


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
