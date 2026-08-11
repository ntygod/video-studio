from fastapi import APIRouter, Request

from app.store import UnitOfWork

router = APIRouter(tags=["operations"])


@router.get("/api/projects/{project_id}/operations")
def list_operations(project_id: str, request: Request, status: str | None = None, limit: int = 100):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        return uow.operations.list(project_id, status=status, limit=limit)


@router.get("/api/operations/{operation_id}")
def get_operation(operation_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.operations.get(operation_id)
