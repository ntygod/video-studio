"""Adopt the original ORM schema as the Alembic baseline."""

from alembic import op

from app.store import models  # noqa: F401
from app.store.database import Base

revision = "20260811_0001"
down_revision = None
branch_labels = None
depends_on = None

BASELINE_TABLES = frozenset(
    {
        "projects",
        "creative_units",
        "conversations",
        "messages",
        "artifacts",
        "artifact_versions",
        "change_proposals",
        "provider_profiles",
        "model_profiles",
        "assets",
        "jobs",
        "job_events",
        "agent_turns",
        "agent_steps",
    }
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in Base.metadata.sorted_tables:
        if table.name in BASELINE_TABLES:
            table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for trigger in (
            "trg_units_fts_insert",
            "trg_units_fts_update",
            "trg_units_fts_delete",
            "trg_artifacts_fts_insert",
            "trg_artifacts_fts_update",
            "trg_artifacts_fts_delete",
            "trg_artifact_versions_fts_update",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
        op.execute("DROP TABLE IF EXISTS units_fts")
        op.execute("DROP TABLE IF EXISTS artifacts_fts")
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in BASELINE_TABLES:
            table.drop(bind=bind, checkfirst=True)
