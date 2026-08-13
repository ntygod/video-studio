"""Add durable external Provider request ledger."""

from alembic import op
import sqlalchemy as sa

revision = "20260813_0015"
down_revision = "20260812_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_provider_requests",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("request_key", sa.String(length=240), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("provider_profile_id", sa.String(length=64), nullable=False),
        sa.Column("provider_name", sa.String(length=200), nullable=False),
        sa.Column("adapter", sa.String(length=100), nullable=False),
        sa.Column("model_profile_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=300), nullable=False),
        sa.Column("capability_type", sa.String(length=50), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_summary_json", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=240), nullable=False),
        sa.Column("idempotency_header", sa.String(length=100), nullable=False),
        sa.Column("provider_request_id", sa.String(length=300), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column("usage_json", sa.Text(), nullable=False),
        sa.Column("cost_entry_id", sa.String(length=64), nullable=True),
        sa.Column("dispatch_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("resolution", sa.String(length=40), nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=False),
        sa.Column("resolved_by_type", sa.String(length=40), nullable=False),
        sa.Column("resolved_by_id", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("dispatched_at", sa.Float(), nullable=True),
        sa.Column("response_started_at", sa.Float(), nullable=True),
        sa.Column("completed_at", sa.Float(), nullable=True),
        sa.Column("failed_at", sa.Float(), nullable=True),
        sa.Column("resolved_at", sa.Float(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["runtime_task_attempts.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["cost_entry_id"],
            ["runtime_cost_entries.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "plan_id",
            "request_key",
            name="uq_runtime_provider_request_plan_key",
        ),
    )
    op.create_index(
        "ix_runtime_provider_requests_plan_id",
        "runtime_provider_requests",
        ["plan_id"],
    )
    op.create_index(
        "ix_runtime_provider_requests_task_id",
        "runtime_provider_requests",
        ["task_id"],
    )
    op.create_index(
        "ix_runtime_provider_requests_status",
        "runtime_provider_requests",
        ["status"],
    )
    op.create_index(
        "ix_runtime_provider_requests_plan_created",
        "runtime_provider_requests",
        ["plan_id", "created_at"],
    )
    op.create_index(
        "ix_runtime_provider_requests_status_updated",
        "runtime_provider_requests",
        ["status", "updated_at"],
    )
    op.create_index(
        "ix_runtime_provider_requests_provider_id",
        "runtime_provider_requests",
        ["provider_request_id"],
    )


def downgrade() -> None:
    op.drop_table("runtime_provider_requests")
