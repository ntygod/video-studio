from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/{project_id}/{path:path}")
def media_file(project_id: str, path: str, request: Request):
    media_root = request.app.state.media_store.root.resolve()
    target = (media_root / project_id / path).resolve()
    if media_root not in target.parents:
        raise HTTPException(400, "invalid media path")
    if not target.is_file():
        raise HTTPException(404, "media not found")
    return FileResponse(target)
