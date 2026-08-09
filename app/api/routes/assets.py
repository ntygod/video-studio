from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel, Field

from app.store import UnitOfWork
from app.store.media_store import MediaStore

router = APIRouter(tags=["assets"])


class AssetCreate(BaseModel):
    unit_id: str | None = None
    shot_id: str | None = None
    kind: str = "reference"
    name: str = ""
    uri: str
    mime_type: str = "application/octet-stream"
    sha256: str = ""
    parent_asset_id: str | None = None
    generation: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.get("/api/projects/{project_id}/assets")
def list_assets(project_id: str, request: Request, unit_id: str | None = None):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        return uow.assets.list(project_id, unit_id=unit_id)


@router.post("/api/projects/{project_id}/assets", status_code=201)
def post_asset(project_id: str, data: AssetCreate, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        if data.unit_id:
            unit = uow.units.get(data.unit_id)
            if unit.project_id != project_id:
                from app.store.repositories import NotFoundError

                raise NotFoundError(data.unit_id)
        return uow.assets.create({**data.model_dump(), "project_id": project_id})


@router.post("/api/projects/{project_id}/assets/upload", status_code=201)
def upload_asset(
    project_id: str,
    request: Request,
    file: UploadFile = File(...),
    kind: str = Form("reference"),
    name: str = Form(""),
    unit_id: str | None = Form(None),
):
    media_store: MediaStore = request.app.state.media_store
    suffix = "." + (file.filename or "bin").rsplit(".", 1)[-1].lower()
    data = file.file.read()
    uri, sha256 = media_store.write_bytes(project_id, data, suffix, unit_id=unit_id)
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        if unit_id:
            unit = uow.units.get(unit_id)
            if unit.project_id != project_id:
                from app.store.repositories import NotFoundError

                raise NotFoundError(unit_id)
        mime_type = file.content_type or "application/octet-stream"
        return uow.assets.create(
            {
                "project_id": project_id,
                "unit_id": unit_id,
                "kind": kind,
                "name": name or (file.filename or "upload"),
                "uri": uri,
                "mime_type": mime_type,
                "sha256": sha256,
            }
        )


@router.get("/api/assets/{asset_id}")
def get_asset(asset_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.assets.get(asset_id)


@router.delete("/api/assets/{asset_id}")
def delete_asset(asset_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        asset = uow.assets.get(asset_id)
        uow.assets.delete(asset_id)
    request.app.state.media_store.delete_asset(asset["uri"])
    return {"ok": True}
