from .artifact_repository import SchemaAwareArtifactRepository
from .asset_repository import SemanticAssetRepository
from .operation_repository import OperationLogRepository
from .repositories import (
    AgentTurnRepository,
    ConversationRepository,
    JobRepository,
    ProjectRepository,
    ProposalRepository,
    ProviderRepository,
    SearchRepository,
)
from .semantic_graph_repository import (
    SemanticArtifactGraphRepository,
)
from .unit_repository import SemanticUnitRepository


class UnitOfWork:
    def __init__(self, database):
        self.database = database
        self.session = None

    def __enter__(self):
        self.session = self.database.session_factory()
        self.projects = ProjectRepository(self.session)
        self.units = SemanticUnitRepository(self.session)
        self.conversations = ConversationRepository(self.session)
        self.artifacts = SchemaAwareArtifactRepository(self.session)
        self.proposals = ProposalRepository(self.session)
        self.providers = ProviderRepository(self.session)
        self.assets = SemanticAssetRepository(self.session)
        self.jobs = JobRepository(self.session)
        self.agent_turns = AgentTurnRepository(self.session)
        self.operations = OperationLogRepository(self.session)
        self.artifact_graph = SemanticArtifactGraphRepository(
            self.session
        )
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
