"""Adopt the current ORM schema as the Alembic baseline."""

from alembic import op

from app.store import models  # noqa: F401
from app.store.database import Base

revision = "20260811_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


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
    Base.metadata.drop_all(bind=bind)
