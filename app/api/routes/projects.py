from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.application.projects import create_project, create_units, patch_project
from app.domain import CreativeUnit
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
    units: list[UnitCreate]


@router.get("")
def list_projects(request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        projects = [item.model_dump(mode="json") for item in uow.projects.list()]
        summaries = {item["id"]: item for item in uow.projects.summaries()}
        for project in projects:
            project.update(summaries.get(project["id"], {}))
        return projects


@router.post("", status_code=201)
def post_project(data: ProjectCreate, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        project = create_project(uow, **data.model_dump())
        return project.model_dump(mode="json")


@router.get("/{project_id}")
def get_project(project_id: str, request: Request):
    """项目详情瘦身（T3.1）：只回项目本身 + 统计，不再内嵌 units/artifacts/proposals。"""
    with UnitOfWork(request.app.state.database) as uow:
        project = uow.projects.get(project_id)
        return {**project.model_dump(mode="json"), **uow.projects.stats(project_id)}


@router.patch("/{project_id}")
def patch_project_route(project_id: str, data: ProjectPatch, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        project = patch_project(uow, project_id, data.patch, data.expected_revision)
        return project.model_dump(mode="json")


@router.delete("/{project_id}")
def delete_project(project_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.delete(project_id)
    request.app.state.media_store.delete_project(project_id)
    return {"ok": True}


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
def post_units(project_id: str, data: UnitsCreate, request: Request):
    definitions = []
    for index, unit in enumerate(data.units):
        payload = unit.model_dump(exclude_none=True)
        payload.setdefault("order_index", float(index))
        definitions.append(payload)
    with UnitOfWork(request.app.state.database) as uow:
        result = create_units(uow, project_id, definitions)
        return [item.model_dump(mode="json") for item in result]


@router.get("/{project_id}/units/{unit_id}")
def get_unit(project_id: str, unit_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        unit = uow.units.get(unit_id)
        if unit.project_id != project_id:
            from app.store.repositories import NotFoundError

            raise NotFoundError(unit_id)
        return {
            **unit.model_dump(mode="json"),
            "children": [
                item.model_dump(mode="json")
                for item in uow.units.list(project_id, parent_id=unit_id)
            ],
            "artifacts": uow.artifacts.list(
                project_id, unit_id=unit_id, include_payload=False
            ),
        }


@router.patch("/{project_id}/units/{unit_id}")
def patch_unit(project_id: str, unit_id: str, patch: dict[str, Any], request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        unit = uow.units.get(unit_id)
        if unit.project_id != project_id:
            from app.store.repositories import NotFoundError

            raise NotFoundError(unit_id)
        data = unit.model_dump(mode="json")
        for key, value in patch.items():
            if key in {
                "parent_id",
                "unit_type",
                "order_index",
                "title",
                "summary",
                "stage",
                "continuity_summary",
                "custom_fields",
            }:
                data[key] = value
        return uow.units.update(CreativeUnit.model_validate(data)).model_dump(mode="json")


@router.delete("/{project_id}/units/{unit_id}")
def delete_unit(project_id: str, unit_id: str, request: Request):
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
    """FTS5 全文检索（T3.2），同时是 Agent search 工具的后端。"""
    from app.store.repositories import NotFoundError

    with UnitOfWork(request.app.state.database) as uow:
        try:
            uow.projects.get(project_id)
        except NotFoundError:
            raise
        return uow.search.search(project_id, q, kind=type, limit=limit)
