from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel, Field

from app.api.command_context import command_context
from app.application.commands import (
    CreateAssetCommand,
    CreateUploadedAssetCommand,
    DeleteAssetCommand,
    MAX_UPLOAD_BYTES,
    PatchAssetScopeCommand,
    get_command_bus,
)
from app.store import UnitOfWork

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


class AssetScopePatch(BaseModel):
    unit_id: str | None = None
    shot_id: str | None = None


@router.get("/api/projects/{project_id}/assets")
def list_assets(
    project_id: str,
    request: Request,
    unit_id: str | None = None,
    kind: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
):
    with UnitOfWork(request.app.state.database) as uow:
        uow.projects.get(project_id)
        return uow.assets.list_page(
            project_id,
            unit_id=unit_id,
            kind=kind,
            limit=limit,
            cursor=cursor,
        )


@router.post("/api/projects/{project_id}/assets", status_code=201)
def post_asset(
    project_id: str,
    data: AssetCreate,
    request: Request,
):
    result = get_command_bus(request.app).execute(
        CreateAssetCommand(
            project_id=project_id,
            **data.model_dump(),
        ),
        command_context(request),
    )
    return result.result


@router.post(
    "/api/projects/{project_id}/assets/upload",
    status_code=201,
)
def upload_asset(
    project_id: str,
    request: Request,
    file: UploadFile = File(...),
    kind: str = Form("reference"),
    name: str = Form(""),
    unit_id: str | None = Form(None),
):
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    execution = get_command_bus(request.app).execute(
        CreateUploadedAssetCommand(
            project_id=project_id,
            data=content,
            filename=file.filename or "upload.bin",
            media_store=request.app.state.media_store,
            unit_id=unit_id,
            kind=kind,
            name=name,
            mime_type=(
                file.content_type or "application/octet-stream"
            ),
        ),
        command_context(request),
    )
    return execution.result


@router.get("/api/assets/{asset_id}")
def get_asset(asset_id: str, request: Request):
    with UnitOfWork(request.app.state.database) as uow:
        return uow.assets.get(asset_id)


@router.patch("/api/assets/{asset_id}")
def patch_asset(
    asset_id: str,
    data: AssetScopePatch,
    request: Request,
):
    fields = data.model_fields_set
    result = get_command_bus(request.app).execute(
        PatchAssetScopeCommand(
            asset_id=asset_id,
            unit_id=data.unit_id,
            shot_id=data.shot_id,
            set_unit_id="unit_id" in fields,
            set_shot_id="shot_id" in fields,
        ),
        command_context(request),
    )
    return result.result


@router.delete("/api/assets/{asset_id}")
def delete_asset(asset_id: str, request: Request):
    return get_command_bus(request.app).execute(
        DeleteAssetCommand(
            asset_id=asset_id,
            media_store=request.app.state.media_store,
        ),
        command_context(request),
    ).result
