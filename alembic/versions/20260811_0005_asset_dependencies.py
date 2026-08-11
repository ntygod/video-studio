"""Add durable Asset inputs to the Artifact graph."""

from alembic import op
import sqlalchemy as sa

revision = "20260811_0005"
down_revision = "20260811_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_dependencies",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("upstream_asset_id", sa.String(length=64), nullable=False),
        sa.Column(
            "upstream_asset_snapshot_json",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "downstream_artifact_id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "downstream_version_id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "dependency_type",
            sa.String(length=80),
            nullable=False,
        ),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["downstream_artifact_id"],
            ["artifacts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["downstream_version_id"],
            ["artifact_versions.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "upstream_asset_id",
            "downstream_version_id",
            "dependency_type",
            name="uq_asset_dependency_edge",
        ),
    )
    op.create_index(
        "ix_asset_dependencies_project_id",
        "asset_dependencies",
        ["project_id"],
    )
    op.create_index(
        "ix_asset_dependencies_upstream_asset_id",
        "asset_dependencies",
        ["upstream_asset_id"],
    )
    op.create_index(
        "ix_asset_dependencies_downstream_artifact_id",
        "asset_dependencies",
        ["downstream_artifact_id"],
    )
    op.create_index(
        "ix_asset_dependencies_downstream_version_id",
        "asset_dependencies",
        ["downstream_version_id"],
    )
    op.create_index(
        "ix_asset_dependency_project_downstream",
        "asset_dependencies",
        ["project_id", "downstream_artifact_id"],
    )


def downgrade() -> None:
    op.drop_table("asset_dependencies")
