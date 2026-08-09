# -*- coding: utf-8 -*-
"""Video Studio application assembly.

Business behavior lives in application services and routers. The app exposes only
the open project model; the previous Episode/Series/Chat endpoints are intentionally
removed.
"""

from fastapi import FastAPI

from .api.errors import install_error_handlers
from .api.routes import routers
from .application.providers import import_provider_file_once
from .application.workflows import seed_workflows
from .settings import Settings, settings as default_settings
from .store import Database, UnitOfWork
from .store.media_store import MediaStore


def create_app(app_settings: Settings | None = None) -> FastAPI:
    config = app_settings or default_settings
    config.ensure_directories()
    database = Database(config.resolved_database_url())
    database.create_schema()
    media_store = MediaStore(config.media_dir)

    with UnitOfWork(database) as uow:
        import_provider_file_once(uow, config.data_dir / "providers.json")
        seed_workflows(uow)

    app = FastAPI(
        title=config.app_name,
        version=config.app_version,
        description="Open creative project, artifact, asset and timeline platform",
    )
    app.state.settings = config
    app.state.database = database
    app.state.media_store = media_store
    install_error_handlers(app)
    for router in routers:
        app.include_router(router)
    return app


app = create_app()
