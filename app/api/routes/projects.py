from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.command_context import command_context
from app.application.commands import (
    CreateProjectCommand,
    CreateUnitsCommand,
    DeleteProjectCommand,
    PatchProjectCommand,
    PatchUnitCommand,
    get_command_bus,
)
from app.store import UnitOfWork

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    title: str = "未命名项目"
    project_type: str = "freeform"
    workflow_id: str = "freeform"
    concept: str = ""
    format_id: str = "freeform"
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class ProjectPatch(BaseModel):
    expected_revision: int = Field(ge=1)
    patch: dict[str, Any]


class UnitCreate(BaseModel):
    id: str | None = None
    parent_id: str | None = None
    unit_type: str = "unit"
    order_index: float | None = None
    title: str = "未命名单元"
    summary: str = ""
    stage: str = "brief"
    continuity_summary: str = ""
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class UnitsCreate(BaseModel):
    units: list[UnitCreate] = Field(
        min_length=1,
        max_length=500,
    )


@router.get("")
def list_projects(request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        projects = [
            item.model_dump(mode="json")
            for item in uow.projects.list()
        ]
        summaries = {
            item["id"]: item
            for item in uow.projects.summaries()
        }
        for project in projects:
            project.update(summaries.get(project["id"], {}))
        return projects


@router.post("", status_code=201)
def post_project(data: ProjectCreate, request: Request):
    return get_command_bus(request.app).execute(
        CreateProjectCommand(**data.model_dump()),
        command_context(request),
    ).result


@router.get("/{project_id}")
def get_project(project_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        project = uow.projects.get(project_id)
        return {
            **project.model_dump(mode="json"),
            **uow.projects.stats(project_id),
        }


@router.patch("/{project_id}")
def patch_project_route(
    project_id: str,
    data: ProjectPatch,
    request: Request,
):
    return get_command_bus(request.app).execute(
        PatchProjectCommand(
            project_id=project_id,
            patch=data.patch,
            expected_revision=data.expected_revision,
        ),
        command_context(request),
    ).result


@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    request: Request,
    expected_revision: int | None = None,
):
    return get_command_bus(request.app).execute(
        DeleteProjectCommand(
            project_id=project_id,
            media_store=request.app.state.media_store,
            expected_revision=expected_revision,
        ),
        command_context(request),
    ).result


@router.get("/{project_id}/units")
def list_units(
    project_id: str,
    request: Request,
    parent_id: str | None = None,
    depth: int = 1,
    limit: int = 200,
    cursor: str | None = None,
):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        return uow.units.list_page(
            project_id,
            parent_id=parent_id,
            depth=depth,
            limit=limit,
            cursor=cursor,
        )


@router.post("/{project_id}/units", status_code=201)
def post_units(
    project_id: str,
    data: UnitsCreate,
    request: Request,
):
    definitions = []
    for index, unit in enumerate(data.units):
        payload = unit.model_dump(exclude_none=True)
        payload.setdefault("order_index", float(index))
        definitions.append(payload)
    return get_command_bus(request.app).execute(
        CreateUnitsCommand(
            project_id=project_id,
            definitions=definitions,
        ),
        command_context(request),
    ).result


@router.get("/{project_id}/units/{unit_id}")
def get_unit(
    project_id: str,
    unit_id: str,
    request: Request,
):
    with UnitOfWork(request.app.state.database) as uow:
        unit = uow.units.get(unit_id)
        if unit.project_id != project_id:
            from app.store.repositories import NotFoundError

            raise NotFoundError(unit_id)
        return {
            **unit.model_dump(mode="json"),
            "children": [
                item.model_dump(mode="json")
                for item in uow.units.list(
                    project_id,
                    parent_id=unit_id,
                )
            ],
            "artifacts": uow.artifacts.list(
                project_id,
                unit_id=unit_id,
                include_payload=False,
            ),
        }


@router.patch("/{project_id}/units/{unit_id}")
def patch_unit(
    project_id: str,
    unit_id: str,
    patch: dict[str, Any],
    request: Request,
    expected_updated_at: float | None = None,
):
    return get_command_bus(request.app).execute(
        PatchUnitCommand(
            project_id=project_id,
            unit_id=unit_id,
            patch=patch,
            expected_updated_at=expected_updated_at,
        ),
        command_context(request),
    ).result


@router.delete("/{project_id}/units/{unit_id}")
def delete_unit(
    project_id: str,
    unit_id: str,
    request: Request,
):
    # Cascading unit deletion needs a subtree snapshot before it can gain a
    # safe inverse operation. Keep it outside CommandBus until that exists.
    with UnitOfWork(request.app.state.database) as uow:
        unit = uow.units.get(unit_id)
        if unit.project_id != project_id:
            from app.store.repositories import NotFoundError

            raise NotFoundError(unit_id)
        uow.units.delete(unit_id)
    return {"ok": True}


@router.get("/{project_id}/search")
def search_project(
    project_id: str,
    request: Request,
    q: str = "",
    type: str = "all",
    limit: int = 20,
):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        return uow.search.search(
            project_id,
            q,
            kind=type,
            limit=limit,
        )
