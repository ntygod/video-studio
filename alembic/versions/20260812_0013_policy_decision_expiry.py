"""Add expiry deadlines for durable runtime policy decisions."""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa

revision = "20260812_0013"
down_revision = "20260812_0012"
branch_labels = None
depends_on = None

AGENT_PLAN_KIND = "agent.turn"
DEFAULT_APPROVAL_TTL_SECONDS = 86_400.0
MAX_APPROVAL_TTL_SECONDS = 604_800.0


def _ttl_seconds(policy_json) -> float:
    try:
        policy = json.loads(policy_json or "{}")
    except (TypeError, ValueError):
        policy = {}
    if not isinstance(policy, dict):
        policy = {}
    try:
        value = float(
            policy.get(
                "approval_ttl_seconds",
                DEFAULT_APPROVAL_TTL_SECONDS,
            )
        )
    except (TypeError, ValueError):
        value = DEFAULT_APPROVAL_TTL_SECONDS
    return max(1.0, min(value, MAX_APPROVAL_TTL_SECONDS))


def upgrade() -> None:
    op.add_column(
        "runtime_policy_decisions",
        sa.Column("expires_at", sa.Float(), nullable=True),
    )
    op.create_index(
        "ix_runtime_policy_pending_expiry",
        "runtime_policy_decisions",
        ["status", "expires_at"],
    )

    bind = op.get_bind()
    plans = list(
        bind.execute(
            sa.text(
                """
                SELECT id, kind, policy_json
                FROM runtime_plans
                """
            )
        ).mappings()
    )
    policy_by_plan = {}
    for plan in plans:
        try:
            policy = json.loads(plan["policy_json"] or "{}")
        except (TypeError, ValueError):
            policy = {}
        if not isinstance(policy, dict):
            policy = {}
        if (
            plan["kind"] == AGENT_PLAN_KIND
            and "approval_ttl_seconds" not in policy
        ):
            policy["approval_ttl_seconds"] = (
                DEFAULT_APPROVAL_TTL_SECONDS
            )
            bind.execute(
                sa.text(
                    """
                    UPDATE runtime_plans
                    SET policy_json = :policy_json
                    WHERE id = :plan_id
                    """
                ),
                {
                    "plan_id": plan["id"],
                    "policy_json": json.dumps(
                        policy,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                },
            )
        policy_by_plan[plan["id"]] = policy

    pending = list(
        bind.execute(
            sa.text(
                """
                SELECT id, plan_id, created_at
                FROM runtime_policy_decisions
                WHERE status = 'pending' AND expires_at IS NULL
                """
            )
        ).mappings()
    )
    for decision in pending:
        policy = policy_by_plan.get(decision["plan_id"], {})
        ttl = _ttl_seconds(json.dumps(policy))
        bind.execute(
            sa.text(
                """
                UPDATE runtime_policy_decisions
                SET expires_at = :expires_at
                WHERE id = :decision_id
                  AND status = 'pending'
                  AND expires_at IS NULL
                """
            ),
            {
                "decision_id": decision["id"],
                "expires_at": float(decision["created_at"]) + ttl,
            },
        )


def downgrade() -> None:
    op.drop_index(
        "ix_runtime_policy_pending_expiry",
        table_name="runtime_policy_decisions",
    )
    op.drop_column("runtime_policy_decisions", "expires_at")
