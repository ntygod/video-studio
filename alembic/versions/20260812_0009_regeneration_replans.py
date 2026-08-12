"""Add immutable regeneration replan lineage."""

from alembic import op
import sqlalchemy as sa

revision = "20260812_0009"
down_revision = "20260812_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "regeneration_plan_replans",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("source_plan_id", sa.String(length=64), nullable=False),
        sa.Column("target_plan_id", sa.String(length=64), nullable=False),
        sa.Column("source_status", sa.String(length=40), nullable=False),
        sa.Column("source_execution_attempt", sa.Integer(), nullable=False),
        sa.Column(
            "target_snapshot_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_plan_id"],
            ["regeneration_plans.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_plan_id"],
            ["regeneration_plans.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "source_plan_id",
            name="uq_regeneration_replan_source",
        ),
        sa.UniqueConstraint(
            "target_plan_id",
            name="uq_regeneration_replan_target",
        ),
    )
    op.create_index(
        "ix_regeneration_plan_replans_project_id",
        "regeneration_plan_replans",
        ["project_id"],
    )
    op.create_index(
        "ix_regeneration_plan_replans_source_plan_id",
        "regeneration_plan_replans",
        ["source_plan_id"],
    )
    op.create_index(
        "ix_regeneration_plan_replans_target_plan_id",
        "regeneration_plan_replans",
        ["target_plan_id"],
    )
    op.create_index(
        "ix_regeneration_replans_project_created",
        "regeneration_plan_replans",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("regeneration_plan_replans")
