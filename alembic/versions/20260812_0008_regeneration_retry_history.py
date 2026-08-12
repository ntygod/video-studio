"""Add execution attempts and retry history to regeneration plans."""

from alembic import op
import sqlalchemy as sa

revision = "20260812_0008"
down_revision = "20260812_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("regeneration_plans") as batch:
        batch.add_column(
            sa.Column(
                "execution_attempt",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
    with op.batch_alter_table("regeneration_plan_steps") as batch:
        batch.add_column(
            sa.Column(
                "execution_attempt",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch.add_column(
            sa.Column(
                "attempt_history_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("regeneration_plan_steps") as batch:
        batch.drop_column("attempt_history_json")
        batch.drop_column("execution_attempt")
    with op.batch_alter_table("regeneration_plans") as batch:
        batch.drop_column("execution_attempt")
