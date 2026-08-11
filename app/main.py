# -*- coding: utf-8 -*-
"""Video Studio application assembly.

Business behavior lives in application services and routers. The app exposes
only the open project model; the previous Episode/Series/Chat endpoints are
intentionally removed.
"""

from fastapi import FastAPI

from .api.errors import install_error_handlers
from .api.logging import install_request_logging
from .api.routes import routers
from .application.commands.recovery import (
    recover_interrupted_operations,
)
from .application.providers import import_provider_file_once
from .settings import Settings, settings as default_settings
from .store import Database, UnitOfWork
from .store.media_store import MediaStore


def create_app(app_settings: Settings | None = None) -> FastAPI:
    config = app_settings or default_settings
    config.ensure_directories()
    database = Database(config.resolved_database_url())
    database.create_schema()
    media_store = MediaStore(
        config.media_dir,
        ffmpeg_path=config.ffmpeg_path,
        ffprobe_path=config.ffprobe_path,
    )
    recover_interrupted_operations(
        database,
        media_store=media_store,
    )

    with UnitOfWork(database) as uow:
        import_provider_file_once(
            uow,
            config.data_dir / "providers.json",
        )

    app = FastAPI(
        title=config.app_name,
        version=config.app_version,
        description=(
            "Open creative project, artifact, asset and timeline platform"
        ),
    )
    app.state.settings = config
    app.state.database = database
    app.state.media_store = media_store
    install_error_handlers(app)
    install_request_logging(app)
    for router in routers:
        app.include_router(router)
    return app


app = create_app()
