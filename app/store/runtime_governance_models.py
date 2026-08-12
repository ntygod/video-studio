"""Database rows for durable runtime policy decisions and budget ledgers.

The mappings share the private runtime-control registry. Alembic owns their
DDL; historical ``Base.metadata.create_all`` fixtures must continue to model
the pre-control-plane schema accurately.
"""

from sqlalchemy import Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .runtime_control_models import runtime_control_registry


@runtime_control_registry.mapped
class RuntimePolicyDecisionRow:
    """One stable policy decision for one logical runtime action."""

    __tablename__ = "runtime_policy_decisions"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "action_key",
            name="uq_runtime_policy_plan_action",
        ),
        Index(
            "ix_runtime_policy_plan_status",
            "plan_id",
            "status",
        ),
        Index(
            "ix_runtime_policy_task_status",
            "task_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action_key: Mapped[str] = mapped_column(String(240), nullable=False)
    action_type: Mapped[str] = mapped_column(String(120), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(30), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    requested_by_type: Mapped[str] = mapped_column(String(40), nullable=False)
    requested_by_id: Mapped[str] = mapped_column(String(160), nullable=False)
    decided_by_type: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    decided_by_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    decision_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    decided_at: Mapped[float | None] = mapped_column(Float, nullable=True)


@runtime_control_registry.mapped
class RuntimeBudgetLedgerRow:
    """Current aggregate usage for one RuntimePlan."""

    __tablename__ = "runtime_budget_ledgers"

    plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_microunits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


@runtime_control_registry.mapped
class RuntimeBudgetTaskUsageRow:
    """Last absolute usage reported by one Task, used to compute safe deltas."""

    __tablename__ = "runtime_budget_task_usage"
    __table_args__ = (
        Index("ix_runtime_budget_task_usage_plan", "plan_id"),
    )

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_microunits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


@runtime_control_registry.mapped
class RuntimeBudgetConsumptionRow:
    """Exactly-once non-token budget consumption, such as a logical tool call."""

    __tablename__ = "runtime_budget_consumptions"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "consumption_key",
            name="uq_runtime_budget_plan_consumption",
        ),
        Index("ix_runtime_budget_consumptions_task", "task_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    consumption_key: Mapped[str] = mapped_column(String(240), nullable=False)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_microunits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


__all__ = [
    "RuntimeBudgetConsumptionRow",
    "RuntimeBudgetLedgerRow",
    "RuntimeBudgetTaskUsageRow",
    "RuntimePolicyDecisionRow",
]
