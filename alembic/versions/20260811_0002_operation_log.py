"""Add durable semantic operation audit."""

from alembic import op
import sqlalchemy as sa

revision = "20260811_0002"
down_revision = "20260811_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "operation_logs" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "operation_logs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=True),
        sa.Column("operation_type", sa.String(length=120), nullable=False),
        sa.Column("actor_type", sa.String(length=30), nullable=False, server_default="user"),
        sa.Column("actor_id", sa.String(length=120), nullable=False, server_default="local"),
        sa.Column("request_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("turn_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("target_type", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("target_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("risk_level", sa.String(length=20), nullable=False, server_default="low"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("arguments_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("preconditions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("affected_entities_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("inverse_json", sa.Text(), nullable=False, server_default="null"),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="null"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("completed_at", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_operation_idempotency_key"),
    )
    op.create_index("ix_operation_logs_project_id", "operation_logs", ["project_id"])
    op.create_index("ix_operation_logs_operation_type", "operation_logs", ["operation_type"])
    op.create_index("ix_operation_logs_turn_id", "operation_logs", ["turn_id"])
    op.create_index("ix_operation_logs_status", "operation_logs", ["status"])
    op.create_index("ix_operation_project_created", "operation_logs", ["project_id", "created_at"])
    op.create_index("ix_operation_status_created", "operation_logs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_table("operation_logs")
