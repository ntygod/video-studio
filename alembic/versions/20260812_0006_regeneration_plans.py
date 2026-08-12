"""Add durable regeneration plans and steps."""

from alembic import op
import sqlalchemy as sa

revision = "20260812_0006"
down_revision = "20260811_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "regeneration_plans",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("root_artifact_ids_json", sa.Text(), nullable=False),
        sa.Column("include_downstream", sa.Boolean(), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("started_at", sa.Float(), nullable=True),
        sa.Column("completed_at", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_regeneration_plans_project_id",
        "regeneration_plans",
        ["project_id"],
    )
    op.create_index(
        "ix_regeneration_plans_status",
        "regeneration_plans",
        ["status"],
    )
    op.create_index(
        "ix_regeneration_plans_snapshot_sha256",
        "regeneration_plans",
        ["snapshot_sha256"],
    )
    op.create_index(
        "ix_regeneration_plans_project_status",
        "regeneration_plans",
        ["project_id", "status"],
    )

    op.create_table(
        "regeneration_plan_steps",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_id", sa.String(length=64), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("artifact_kind", sa.String(length=100), nullable=False),
        sa.Column("artifact_name", sa.String(length=300), nullable=False),
        sa.Column("unit_id", sa.String(length=64), nullable=True),
        sa.Column("expected_version_id", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column(
            "can_execute_automatically",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column(
            "depends_on_artifact_ids_json",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "external_upstream_artifact_ids_json",
            sa.Text(),
            nullable=False,
        ),
        sa.Column("blockers_json", sa.Text(), nullable=False),
        sa.Column("missing_asset_ids_json", sa.Text(), nullable=False),
        sa.Column(
            "direct_missing_asset_ids_json",
            sa.Text(),
            nullable=False,
        ),
        sa.Column("source_job_id", sa.String(length=64), nullable=True),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("input_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("started_at", sa.Float(), nullable=True),
        sa.Column("completed_at", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["regeneration_plans.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "plan_id",
            "artifact_id",
            name="uq_regeneration_plan_artifact",
        ),
    )
    op.create_index(
        "ix_regeneration_plan_steps_plan_id",
        "regeneration_plan_steps",
        ["plan_id"],
    )
    op.create_index(
        "ix_regeneration_plan_steps_project_id",
        "regeneration_plan_steps",
        ["project_id"],
    )
    op.create_index(
        "ix_regeneration_plan_steps_artifact_id",
        "regeneration_plan_steps",
        ["artifact_id"],
    )
    op.create_index(
        "ix_regeneration_plan_steps_expected_version_id",
        "regeneration_plan_steps",
        ["expected_version_id"],
    )
    op.create_index(
        "ix_regeneration_plan_steps_status",
        "regeneration_plan_steps",
        ["status"],
    )
    op.create_index(
        "ix_regeneration_plan_steps_job_id",
        "regeneration_plan_steps",
        ["job_id"],
    )
    op.create_index(
        "ix_regeneration_steps_plan_order",
        "regeneration_plan_steps",
        ["plan_id", "order_index"],
    )
    op.create_index(
        "ix_regeneration_steps_plan_status",
        "regeneration_plan_steps",
        ["plan_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("regeneration_plan_steps")
    op.drop_table("regeneration_plans")
