"""Add durable runtime policy decisions and budget ledgers."""

from __future__ import annotations

import json
import time

from alembic import op
import sqlalchemy as sa

revision = "20260812_0012"
down_revision = "20260812_0011"
branch_labels = None
depends_on = None

AGENT_PLAN_KIND = "agent.turn"
DEFAULT_AGENT_POLICY = {
    "version": "agent-runtime-policy@1",
    "confirmation_risk_levels": ["high"],
    "denied_actions": [],
    "allowed_actions": [],
}
DEFAULT_AGENT_BUDGET = {
    "max_prompt_tokens": 120_000,
    "max_completion_tokens": 60_000,
    "max_total_tokens": 160_000,
    "max_tool_calls": 12,
    "max_wall_seconds": 900,
}


def _nonnegative_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def upgrade() -> None:
    op.create_table(
        "runtime_policy_decisions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("action_key", sa.String(length=240), nullable=False),
        sa.Column("action_type", sa.String(length=120), nullable=False),
        sa.Column("risk_level", sa.String(length=30), nullable=False),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=False),
        sa.Column("requested_by_type", sa.String(length=40), nullable=False),
        sa.Column("requested_by_id", sa.String(length=160), nullable=False),
        sa.Column("decided_by_type", sa.String(length=40), nullable=False),
        sa.Column("decided_by_id", sa.String(length=160), nullable=False),
        sa.Column("decision_note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("decided_at", sa.Float(), nullable=True),
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
            "plan_id",
            "action_key",
            name="uq_runtime_policy_plan_action",
        ),
    )
    op.create_index(
        "ix_runtime_policy_decisions_plan_id",
        "runtime_policy_decisions",
        ["plan_id"],
    )
    op.create_index(
        "ix_runtime_policy_decisions_task_id",
        "runtime_policy_decisions",
        ["task_id"],
    )
    op.create_index(
        "ix_runtime_policy_decisions_status",
        "runtime_policy_decisions",
        ["status"],
    )
    op.create_index(
        "ix_runtime_policy_plan_status",
        "runtime_policy_decisions",
        ["plan_id", "status"],
    )
    op.create_index(
        "ix_runtime_policy_task_status",
        "runtime_policy_decisions",
        ["task_id", "status"],
    )

    op.create_table(
        "runtime_budget_ledgers",
        sa.Column("plan_id", sa.String(length=64), primary_key=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("cost_microunits", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["runtime_plans.id"],
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "runtime_budget_task_usage",
        sa.Column("task_id", sa.String(length=64), primary_key=True),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_microunits", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["runtime_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["runtime_plans.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_runtime_budget_task_usage_plan",
        "runtime_budget_task_usage",
        ["plan_id"],
    )

    op.create_table(
        "runtime_budget_consumptions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("consumption_key", sa.String(length=240), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("cost_microunits", sa.Integer(), nullable=False),
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
        sa.UniqueConstraint(
            "plan_id",
            "consumption_key",
            name="uq_runtime_budget_plan_consumption",
        ),
    )
    op.create_index(
        "ix_runtime_budget_consumptions_plan_id",
        "runtime_budget_consumptions",
        ["plan_id"],
    )
    op.create_index(
        "ix_runtime_budget_consumptions_task",
        "runtime_budget_consumptions",
        ["task_id"],
    )

    bind = op.get_bind()
    now = time.time()
    plans = list(
        bind.execute(
            sa.text(
                """
                SELECT id, kind, policy_json, budget_json, usage_json
                FROM runtime_plans
                """
            )
        ).mappings()
    )
    for plan in plans:
        if plan["kind"] == AGENT_PLAN_KIND:
            try:
                stored_policy = json.loads(plan["policy_json"] or "{}")
            except (TypeError, ValueError):
                stored_policy = {}
            try:
                stored_budget = json.loads(plan["budget_json"] or "{}")
            except (TypeError, ValueError):
                stored_budget = {}
            if not isinstance(stored_policy, dict):
                stored_policy = {}
            if not isinstance(stored_budget, dict):
                stored_budget = {}
            policy = {**DEFAULT_AGENT_POLICY, **stored_policy}
            budget = {**DEFAULT_AGENT_BUDGET, **stored_budget}
            bind.execute(
                sa.text(
                    """
                    UPDATE runtime_plans
                    SET policy_json = :policy_json, budget_json = :budget_json
                    WHERE id = :plan_id
                    """
                ),
                {
                    "plan_id": plan["id"],
                    "policy_json": json.dumps(
                        policy, ensure_ascii=False, sort_keys=True
                    ),
                    "budget_json": json.dumps(
                        budget, ensure_ascii=False, sort_keys=True
                    ),
                },
            )
        try:
            usage = json.loads(plan["usage_json"] or "{}")
        except (TypeError, ValueError):
            usage = {}
        if not isinstance(usage, dict):
            usage = {}
        prompt = _nonnegative_int(usage.get("prompt_tokens"))
        completion = _nonnegative_int(usage.get("completion_tokens"))
        tool_calls = _nonnegative_int(usage.get("tool_calls"))
        cost = _nonnegative_int(usage.get("cost_microunits"))
        bind.execute(
            sa.text(
                """
                INSERT INTO runtime_budget_ledgers(
                    plan_id, prompt_tokens, completion_tokens,
                    tool_calls, cost_microunits, created_at, updated_at
                ) VALUES(
                    :plan_id, :prompt_tokens, :completion_tokens,
                    :tool_calls, :cost_microunits, :created_at, :updated_at
                )
                """
            ),
            {
                "plan_id": plan["id"],
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "tool_calls": tool_calls,
                "cost_microunits": cost,
                "created_at": now,
                "updated_at": now,
            },
        )


def downgrade() -> None:
    op.drop_table("runtime_budget_consumptions")
    op.drop_table("runtime_budget_task_usage")
    op.drop_table("runtime_budget_ledgers")
    op.drop_table("runtime_policy_decisions")
