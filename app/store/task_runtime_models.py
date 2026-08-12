"""Generic durable Plan, Task, TaskAttempt, and event rows."""

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class RuntimePlanRow(Base):
    __tablename__ = "runtime_plans"
    __table_args__ = (
        UniqueConstraint(
            "kind",
            "idempotency_key",
            name="uq_runtime_plan_kind_idempotency",
        ),
        Index(
            "ix_runtime_plans_project_status",
            "project_id",
            "status",
        ),
        Index(
            "ix_runtime_plans_kind_status",
            "kind",
            "status",
        ),
        Index(
            "ix_runtime_plans_subject",
            "subject_type",
            "subject_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    subject_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="",
    )
    subject_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(240),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="draft",
        index=True,
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    event_seq: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    input_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    policy_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    budget_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    usage_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    result_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    error: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    started_at: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    completed_at: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )


class RuntimeTaskRow(Base):
    __tablename__ = "runtime_tasks"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "task_key",
            name="uq_runtime_task_plan_key",
        ),
        Index(
            "ix_runtime_tasks_plan_order",
            "plan_id",
            "order_index",
        ),
        Index(
            "ix_runtime_tasks_plan_status",
            "plan_id",
            "status",
        ),
        Index(
            "ix_runtime_tasks_claimable",
            "status",
            "available_at",
            "claim_until",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_key: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
    )
    task_type: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="queued",
        index=True,
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    order_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    depends_on_task_ids_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    payload_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    policy_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    checkpoint_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    result_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    usage_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    error: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    timeout_seconds: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )
    available_at: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        index=True,
    )
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    claim_token: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
    )
    claim_owner: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        default="",
    )
    claim_until: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    claim_attempt: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    started_at: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    completed_at: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )


class RuntimeTaskAttemptRow(Base):
    __tablename__ = "runtime_task_attempts"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "attempt",
            name="uq_runtime_task_attempt",
        ),
        Index(
            "ix_runtime_attempts_plan_started",
            "plan_id",
            "started_at",
        ),
        Index(
            "ix_runtime_attempts_task_status",
            "task_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="running",
        index=True,
    )
    worker_id: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        default="",
    )
    claim_token: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
    )
    checkpoint_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    result_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    usage_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    error: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    retryable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    started_at: Mapped[float] = mapped_column(Float, nullable=False)
    heartbeat_at: Mapped[float] = mapped_column(Float, nullable=False)
    lease_until: Mapped[float] = mapped_column(Float, nullable=False)
    completed_at: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )


class RuntimeTaskEventRow(Base):
    __tablename__ = "runtime_task_events"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "seq",
            name="uq_runtime_event_plan_seq",
        ),
        Index(
            "ix_runtime_events_plan_seq",
            "plan_id",
            "seq",
        ),
        Index(
            "ix_runtime_events_task_created",
            "task_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("runtime_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    attempt_id: Mapped[str | None] = mapped_column(
        ForeignKey("runtime_task_attempts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        index=True,
    )
    payload_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


__all__ = [
    "RuntimePlanRow",
    "RuntimeTaskAttemptRow",
    "RuntimeTaskEventRow",
    "RuntimeTaskRow",
]
