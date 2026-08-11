from . import (
    artifacts, assets, conversations, edit, generate, health, jobs, media,
    operations, projects, proposals, providers, timeline, voice,
)

routers = [
    health.router, projects.router, conversations.router, artifacts.router,
    proposals.router, providers.router, jobs.router, operations.router,
    assets.router, media.router, timeline.router, generate.router,
    voice.router, edit.router,
]

__all__ = ["routers"]
