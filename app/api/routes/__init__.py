from . import (
    artifacts,
    assets,
    conversations,
    dependencies,
    edit,
    generate,
    health,
    jobs,
    media,
    operations,
    projects,
    proposals,
    providers,
    runtime,
    timeline,
    voice,
)

routers = [
    health.router,
    projects.router,
    conversations.router,
    artifacts.router,
    dependencies.router,
    proposals.router,
    providers.router,
    runtime.router,
    jobs.router,
    operations.router,
    assets.router,
    media.router,
    timeline.router,
    generate.router,
    voice.router,
    edit.router,
]

__all__ = ["routers"]
