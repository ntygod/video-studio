from . import (
    artifacts, assets, conversations, dependencies, edit, generate, health,
    jobs, media, operations, projects, proposals, providers,
    regeneration_replans, timeline, voice,
)

routers = [
    health.router, projects.router, conversations.router, artifacts.router,
    dependencies.router, regeneration_replans.router, proposals.router,
    providers.router, jobs.router, operations.router, assets.router,
    media.router, timeline.router, generate.router, voice.router, edit.router,
]

__all__ = ["routers"]
