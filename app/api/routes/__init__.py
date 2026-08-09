from . import artifacts, assets, conversations, edit, generate, health, jobs, media, projects, proposals, providers, timeline, voice, workflows

routers = [
    health.router,
    projects.router,
    conversations.router,
    artifacts.router,
    proposals.router,
    providers.router,
    jobs.router,
    workflows.router,
    assets.router,
    media.router,
    timeline.router,
    generate.router,
    voice.router,
    edit.router,
]

__all__ = ["routers"]
