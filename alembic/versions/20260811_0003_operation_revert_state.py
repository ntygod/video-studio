"""Track semantic operation compensation."""

from alembic import op
import sqlalchemy as sa

revision = "20260811_0003"
down_revision = "20260811_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {
        item["name"]
        for item in sa.inspect(bind).get_columns(
            "operation_logs"
        )
    }
    with op.batch_alter_table("operation_logs") as batch:
        if "reverted_by_operation_id" not in columns:
            batch.add_column(
                sa.Column(
                    "reverted_by_operation_id",
                    sa.String(length=64),
                    nullable=True,
                )
            )
        if "reverted_at" not in columns:
            batch.add_column(
                sa.Column(
                    "reverted_at",
                    sa.Float(),
                    nullable=True,
                )
            )
    indexes = {
        item["name"]
        for item in sa.inspect(bind).get_indexes(
            "operation_logs"
        )
    }
    if (
        "ix_operation_logs_reverted_by_operation_id"
        not in indexes
    ):
        op.create_index(
            "ix_operation_logs_reverted_by_operation_id",
            "operation_logs",
            ["reverted_by_operation_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {
        item["name"]
        for item in sa.inspect(bind).get_indexes(
            "operation_logs"
        )
    }
    if (
        "ix_operation_logs_reverted_by_operation_id"
        in indexes
    ):
        op.drop_index(
            "ix_operation_logs_reverted_by_operation_id",
            table_name="operation_logs",
        )
    with op.batch_alter_table("operation_logs") as batch:
        batch.drop_column("reverted_at")
        batch.drop_column("reverted_by_operation_id")
