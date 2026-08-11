from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.store import UnitOfWork

router = APIRouter(tags=["media"])


@router.get("/media/{project_id}/{path:path}")
def media_file(project_id: str, path: str, request: Request):
    media_root = request.app.state.media_store.root.resolve()
    target = (media_root / project_id / path).resolve()
    if media_root not in target.parents:
        raise HTTPException(400, "invalid media path")
    if not target.is_file():
        raise HTTPException(404, "media not found")
    return FileResponse(target)


@router.get("/api/assets/{asset_id}/thumb")
def asset_thumb(asset_id: str, request: Request, w: int = 0):
    """缩略图，无则回落原图（T2.4）。"""
    with UnitOfWork(request.app.state.database) as uow:
        asset = uow.assets.get(asset_id)
    uri = asset.get("thumb_uri") or asset.get("uri")
    if not uri:
        raise HTTPException(404, "asset has no media")
    media_root = request.app.state.media_store.root.resolve()
    relative = uri[len("/media/") :] if uri.startswith("/media/") else uri
    target = (media_root / relative).resolve()
    if media_root not in target.parents:
        raise HTTPException(400, "invalid media path")
    if not target.is_file():
        raise HTTPException(404, "media not found")
    return FileResponse(target)
