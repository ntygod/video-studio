"""Link externally executed Jobs to their owning RuntimePlan and Task."""

from alembic import op
import sqlalchemy as sa

revision = "20260813_0016"
down_revision = "20260813_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(
            sa.Column(
                "runtime_plan_id",
                sa.String(length=64),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "runtime_task_id",
                sa.String(length=64),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "runtime_generation",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
    op.create_index(
        "ix_jobs_runtime_plan_id",
        "jobs",
        ["runtime_plan_id"],
    )
    op.create_index(
        "ix_jobs_runtime_task_id",
        "jobs",
        ["runtime_task_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_runtime_task_id", table_name="jobs")
    op.drop_index("ix_jobs_runtime_plan_id", table_name="jobs")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("runtime_generation")
        batch.drop_column("runtime_task_id")
        batch.drop_column("runtime_plan_id")
