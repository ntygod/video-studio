"""Add the generic durable Plan/Task/TaskAttempt runtime."""

from alembic import op
import sqlalchemy as sa

revision = "20260812_0010"
down_revision = "20260812_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_plans",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=100), nullable=False),
        sa.Column("subject_type", sa.String(length=100), nullable=False),
        sa.Column("subject_id", sa.String(length=64), nullable=False),
        sa.Column(
            "idempotency_key",
            sa.String(length=240),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("event_seq", sa.Integer(), nullable=False),
        sa.Column("input_json", sa.Text(), nullable=False),
        sa.Column("policy_json", sa.Text(), nullable=False),
        sa.Column("budget_json", sa.Text(), nullable=False),
        sa.Column("usage_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
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
        sa.UniqueConstraint(
            "kind",
            "idempotency_key",
            name="uq_runtime_plan_kind_idempotency",
        ),
    )
    op.create_index(
        "ix_runtime_plans_project_id",
        "runtime_plans",
        ["project_id"],
    )
    op.create_index(
        "ix_runtime_plans_kind",
        "runtime_plans",
        ["kind"],
    )
    op.create_index(
        "ix_runtime_plans_status",
        "runtime_plans",
        ["status"],
    )
    op.create_index(
        "ix_runtime_plans_project_status",
        "runtime_plans",
        ["project_id", "status"],
    )
    op.create_index(
        "ix_runtime_plans_kind_status",
        "runtime_plans",
        ["kind", "status"],
    )
    op.create_index(
        "ix_runtime_plans_subject",
        "runtime_plans",
        ["subject_type", "subject_id"],
    )

    op.create_table(
        "runtime_tasks",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("task_key", sa.String(length=160), nullable=False),
        sa.Column("task_type", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column(
            "depends_on_task_ids_json",
            sa.Text(),
            nullable=False,
        ),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("policy_json", sa.Text(), nullable=False),
        sa.Column("checkpoint_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("usage_json", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("available_at", sa.Float(), nullable=False),
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column("claim_token", sa.String(length=64), nullable=False),
        sa.Column(
            "claim_owner",
            sa.String(length=160),
            nullable=False,
        ),
        sa.Column("claim_until", sa.Float(), nullable=True),
        sa.Column("claim_attempt", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("started_at", sa.Float(), nullable=True),
        sa.Column("completed_at", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["runtime_plans.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "plan_id",
            "task_key",
            name="uq_runtime_task_plan_key",
        ),
    )
    op.create_index(
        "ix_runtime_tasks_plan_id",
        "runtime_tasks",
        ["plan_id"],
    )
    op.create_index(
        "ix_runtime_tasks_project_id",
        "runtime_tasks",
        ["project_id"],
    )
    op.create_index(
        "ix_runtime_tasks_task_type",
        "runtime_tasks",
        ["task_type"],
    )
    op.create_index(
        "ix_runtime_tasks_status",
        "runtime_tasks",
        ["status"],
    )
    op.create_index(
        "ix_runtime_tasks_available_at",
        "runtime_tasks",
        ["available_at"],
    )
    op.create_index(
        "ix_runtime_tasks_plan_order",
        "runtime_tasks",
        ["plan_id", "order_index"],
    )
    op.create_index(
        "ix_runtime_tasks_plan_status",
        "runtime_tasks",
        ["plan_id", "status"],
    )
    op.create_index(
        "ix_runtime_tasks_claimable",
        "runtime_tasks",
        ["status", "available_at", "claim_until"],
    )

    op.create_table(
        "runtime_task_attempts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column(
            "worker_id",
            sa.String(length=160),
            nullable=False,
        ),
        sa.Column("claim_token", sa.String(length=64), nullable=False),
        sa.Column("checkpoint_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("usage_json", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.Float(), nullable=False),
        sa.Column("heartbeat_at", sa.Float(), nullable=False),
        sa.Column("lease_until", sa.Float(), nullable=False),
        sa.Column("completed_at", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["runtime_plans.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["runtime_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "task_id",
            "attempt",
            name="uq_runtime_task_attempt",
        ),
    )
    op.create_index(
        "ix_runtime_task_attempts_plan_id",
        "runtime_task_attempts",
        ["plan_id"],
    )
    op.create_index(
        "ix_runtime_task_attempts_task_id",
        "runtime_task_attempts",
        ["task_id"],
    )
    op.create_index(
        "ix_runtime_task_attempts_status",
        "runtime_task_attempts",
        ["status"],
    )
    op.create_index(
        "ix_runtime_attempts_plan_started",
        "runtime_task_attempts",
        ["plan_id", "started_at"],
    )
    op.create_index(
        "ix_runtime_attempts_task_status",
        "runtime_task_attempts",
        ["task_id", "status"],
    )

    op.create_table(
        "runtime_task_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column(
            "event_type",
            sa.String(length=120),
            nullable=False,
        ),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["runtime_plans.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["runtime_tasks.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["runtime_task_attempts.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "plan_id",
            "seq",
            name="uq_runtime_event_plan_seq",
        ),
    )
    op.create_index(
        "ix_runtime_task_events_plan_id",
        "runtime_task_events",
        ["plan_id"],
    )
    op.create_index(
        "ix_runtime_task_events_task_id",
        "runtime_task_events",
        ["task_id"],
    )
    op.create_index(
        "ix_runtime_task_events_attempt_id",
        "runtime_task_events",
        ["attempt_id"],
    )
    op.create_index(
        "ix_runtime_task_events_event_type",
        "runtime_task_events",
        ["event_type"],
    )
    op.create_index(
        "ix_runtime_events_plan_seq",
        "runtime_task_events",
        ["plan_id", "seq"],
    )
    op.create_index(
        "ix_runtime_events_task_created",
        "runtime_task_events",
        ["task_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("runtime_task_events")
    op.drop_table("runtime_task_attempts")
    op.drop_table("runtime_tasks")
    op.drop_table("runtime_plans")
