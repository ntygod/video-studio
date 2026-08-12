"""Durable regeneration plan and step rows."""

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


class RegenerationPlanRow(Base):
    __tablename__ = "regeneration_plans"
    __table_args__ = (
        Index(
            "ix_regeneration_plans_project_status",
            "project_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="draft",
        index=True,
    )
    root_artifact_ids_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    include_downstream: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    snapshot_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    summary_json: Mapped[str] = mapped_column(
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


class RegenerationPlanStepRow(Base):
    __tablename__ = "regeneration_plan_steps"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "artifact_id",
            name="uq_regeneration_plan_artifact",
        ),
        Index(
            "ix_regeneration_steps_plan_order",
            "plan_id",
            "order_index",
        ),
        Index(
            "ix_regeneration_steps_plan_status",
            "plan_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("regeneration_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artifact_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    order_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    artifact_kind: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    artifact_name: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
    )
    unit_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    expected_version_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    can_execute_automatically: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    depends_on_artifact_ids_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    external_upstream_artifact_ids_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    blockers_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    missing_asset_ids_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    direct_missing_asset_ids_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    source_job_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    job_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    input_json: Mapped[str] = mapped_column(
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
