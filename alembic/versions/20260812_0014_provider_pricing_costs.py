"""Add Provider model pricing and immutable Runtime cost entries."""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa

revision = "20260812_0014"
down_revision = "20260812_0013"
branch_labels = None
depends_on = None

AGENT_PLAN_KIND = "agent.turn"
DEFAULT_AGENT_MAX_COST_MICROUNITS = 10_000_000


def upgrade() -> None:
    op.create_table(
        "model_pricing_profiles",
        sa.Column(
            "model_profile_id",
            sa.String(length=64),
            primary_key=True,
        ),
        sa.Column("pricing_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["model_profile_id"],
            ["model_profiles.id"],
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "runtime_cost_entries",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("usage_key", sa.String(length=240), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column(
            "provider_profile_id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("provider_name", sa.String(length=200), nullable=False),
        sa.Column("adapter", sa.String(length=100), nullable=False),
        sa.Column(
            "model_profile_id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("model_id", sa.String(length=300), nullable=False),
        sa.Column(
            "capability_type",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "provider_request_id",
            sa.String(length=300),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=12), nullable=False),
        sa.Column("pricing_sha256", sa.String(length=64), nullable=False),
        sa.Column("pricing_snapshot_json", sa.Text(), nullable=False),
        sa.Column("usage_json", sa.Text(), nullable=False),
        sa.Column("breakdown_json", sa.Text(), nullable=False),
        sa.Column("amount_microunits", sa.Integer(), nullable=False),
        sa.Column("priced", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
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
        sa.UniqueConstraint(
            "plan_id",
            "usage_key",
            name="uq_runtime_cost_plan_usage",
        ),
    )
    op.create_index(
        "ix_runtime_cost_entries_plan_id",
        "runtime_cost_entries",
        ["plan_id"],
    )
    op.create_index(
        "ix_runtime_cost_entries_task_id",
        "runtime_cost_entries",
        ["task_id"],
    )
    op.create_index(
        "ix_runtime_cost_plan_created",
        "runtime_cost_entries",
        ["plan_id", "created_at"],
    )
    op.create_index(
        "ix_runtime_cost_task_created",
        "runtime_cost_entries",
        ["task_id", "created_at"],
    )
    op.create_index(
        "ix_runtime_cost_model",
        "runtime_cost_entries",
        ["model_profile_id"],
    )

    bind = op.get_bind()
    plans = list(
        bind.execute(
            sa.text(
                """
                SELECT id, budget_json
                FROM runtime_plans
                WHERE kind = :kind
                """
            ),
            {"kind": AGENT_PLAN_KIND},
        ).mappings()
    )
    for plan in plans:
        try:
            budget = json.loads(plan["budget_json"] or "{}")
        except (TypeError, ValueError):
            budget = {}
        if not isinstance(budget, dict):
            budget = {}
        if (
            "max_cost_microunits" not in budget
            and "max_cost_usd" not in budget
        ):
            budget["max_cost_microunits"] = (
                DEFAULT_AGENT_MAX_COST_MICROUNITS
            )
            bind.execute(
                sa.text(
                    """
                    UPDATE runtime_plans
                    SET budget_json = :budget_json
                    WHERE id = :plan_id
                    """
                ),
                {
                    "plan_id": plan["id"],
                    "budget_json": json.dumps(
                        budget,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                },
            )


def downgrade() -> None:
    op.drop_table("runtime_cost_entries")
    op.drop_table("model_pricing_profiles")
