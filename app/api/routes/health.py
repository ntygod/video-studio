from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(request: Request):
    settings = request.app.state.settings
    media_root = request.app.state.media_store.root
    return {
        "ok": request.app.state.database.health() and media_root.is_dir(),
        "app": settings.app_name,
        "version": settings.app_version,
        "schema_version": settings.schema_version,
        "db_ok": request.app.state.database.health(),
        "media_root_ok": media_root.is_dir(),
    }

