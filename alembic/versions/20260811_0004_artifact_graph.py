"""Add version-level Artifact dependency graph and freshness."""

from alembic import op
import sqlalchemy as sa

revision = "20260811_0004"
down_revision = "20260811_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifact_dependencies",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("upstream_version_id", sa.String(length=64), nullable=False),
        sa.Column("downstream_artifact_id", sa.String(length=64), nullable=False),
        sa.Column("downstream_version_id", sa.String(length=64), nullable=False),
        sa.Column("dependency_type", sa.String(length=80), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["upstream_version_id"], ["artifact_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["downstream_artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["downstream_version_id"], ["artifact_versions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "upstream_version_id",
            "downstream_version_id",
            "dependency_type",
            name="uq_artifact_dependency_edge",
        ),
    )
    op.create_index("ix_artifact_dependencies_project_id", "artifact_dependencies", ["project_id"])
    op.create_index("ix_artifact_dependencies_upstream_version_id", "artifact_dependencies", ["upstream_version_id"])
    op.create_index("ix_artifact_dependencies_downstream_artifact_id", "artifact_dependencies", ["downstream_artifact_id"])
    op.create_index("ix_artifact_dependencies_downstream_version_id", "artifact_dependencies", ["downstream_version_id"])
    op.create_index(
        "ix_artifact_dependency_project_downstream",
        "artifact_dependencies",
        ["project_id", "downstream_artifact_id"],
    )

    op.create_table(
        "artifact_provenance",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_version_id", sa.String(length=64), nullable=False),
        sa.Column("input_version_ids_json", sa.Text(), nullable=False),
        sa.Column("provider_profile_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=300), nullable=False),
        sa.Column("prompt_version", sa.String(length=120), nullable=False),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("seed", sa.String(length=120), nullable=False),
        sa.Column("task_attempt_id", sa.String(length=64), nullable=False),
        sa.Column("operation_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artifact_version_id"], ["artifact_versions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("artifact_version_id", name="uq_artifact_provenance_version"),
    )
    op.create_index("ix_artifact_provenance_project_id", "artifact_provenance", ["project_id"])
    op.create_index("ix_artifact_provenance_artifact_version_id", "artifact_provenance", ["artifact_version_id"])
    op.create_index("ix_artifact_provenance_operation_id", "artifact_provenance", ["operation_id"])

    op.create_table(
        "artifact_freshness",
        sa.Column("artifact_id", sa.String(length=64), primary_key=True),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("stale_from_version_ids_json", sa.Text(), nullable=False),
        sa.Column("detected_at", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_artifact_freshness_project_id", "artifact_freshness", ["project_id"])
    op.create_index("ix_artifact_freshness_status", "artifact_freshness", ["status"])
    op.create_index(
        "ix_artifact_freshness_project_status",
        "artifact_freshness",
        ["project_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("artifact_freshness")
    op.drop_table("artifact_provenance")
    op.drop_table("artifact_dependencies")
