from .repositories import (
    AgentTurnRepository,
    ArtifactRepository,
    AssetRepository,
    ConversationRepository,
    JobRepository,
    ProjectRepository,
    ProposalRepository,
    ProviderRepository,
    SearchRepository,
    UnitRepository,
)


class UnitOfWork:
    def __init__(self, database):
        self.database = database
        self.session = None

    def __enter__(self):
        self.session = self.database.session_factory()
        self.projects = ProjectRepository(self.session)
        self.units = UnitRepository(self.session)
        self.conversations = ConversationRepository(self.session)
        self.artifacts = ArtifactRepository(self.session)
        self.proposals = ProposalRepository(self.session)
        self.providers = ProviderRepository(self.session)
        self.assets = AssetRepository(self.session)
        self.jobs = JobRepository(self.session)
        self.agent_turns = AgentTurnRepository(self.session)
        self.search = SearchRepository(self.session)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()
