from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.store import UnitOfWork

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class WorkflowCreate(BaseModel):
    name: str
    description: str = ""
    definition: dict[str, Any] = Field(default_factory=dict)


class WorkflowPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    definition: dict[str, Any] | None = None


@router.get("")
def list_workflows(request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.workflows.list()


@router.post("", status_code=201)
def post_workflow(data: WorkflowCreate, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.workflows.create(data.model_dump())


@router.get("/{workflow_id}")
def get_workflow(workflow_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.workflows.get(workflow_id)


@router.patch("/{workflow_id}")
def patch_workflow(workflow_id: str, data: WorkflowPatch, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.workflows.update(workflow_id, data.model_dump(exclude_none=True))


@router.delete("/{workflow_id}")
def delete_workflow(workflow_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        uow.workflows.delete(workflow_id)
    return {"ok": True}
