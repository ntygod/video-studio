"""Add database leases for regeneration plan steps."""

from alembic import op
import sqlalchemy as sa

revision = "20260812_0007"
down_revision = "20260812_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("regeneration_plan_steps") as batch:
        batch.add_column(
            sa.Column(
                "claim_token",
                sa.String(length=64),
                nullable=False,
                server_default="",
            )
        )
        batch.add_column(
            sa.Column(
                "claim_owner",
                sa.String(length=160),
                nullable=False,
                server_default="",
            )
        )
        batch.add_column(
            sa.Column(
                "claim_until",
                sa.Float(),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "claim_attempt",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch.create_index(
            "ix_regeneration_steps_claimable",
            ["plan_id", "status", "claim_until"],
        )


def downgrade() -> None:
    with op.batch_alter_table("regeneration_plan_steps") as batch:
        batch.drop_index("ix_regeneration_steps_claimable")
        batch.drop_column("claim_attempt")
        batch.drop_column("claim_until")
        batch.drop_column("claim_owner")
        batch.drop_column("claim_token")
