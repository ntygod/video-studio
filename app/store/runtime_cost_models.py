"""Immutable Provider-call cost entries for the durable Runtime."""

from sqlalchemy import Boolean, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .runtime_control_models import runtime_control_registry


@runtime_control_registry.mapped
class RuntimeCostEntryRow:
    __tablename__ = "runtime_cost_entries"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "usage_key",
            name="uq_runtime_cost_plan_usage",
        ),
        Index("ix_runtime_cost_plan_created", "plan_id", "created_at"),
        Index("ix_runtime_cost_task_created", "task_id", "created_at"),
        Index("ix_runtime_cost_model", "model_profile_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    usage_key: Mapped[str] = mapped_column(String(240), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(200), nullable=False)
    adapter: Mapped[str] = mapped_column(String(100), nullable=False)
    model_profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(300), nullable=False)
    capability_type: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_request_id: Mapped[str] = mapped_column(String(300), nullable=False)
    currency: Mapped[str] = mapped_column(String(12), nullable=False)
    pricing_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    pricing_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    usage_json: Mapped[str] = mapped_column(Text, nullable=False)
    breakdown_json: Mapped[str] = mapped_column(Text, nullable=False)
    amount_microunits: Mapped[int] = mapped_column(Integer, nullable=False)
    priced: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


__all__ = ["RuntimeCostEntryRow"]
