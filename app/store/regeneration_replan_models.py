"""Immutable lineage between an old regeneration Plan and its replan."""

from sqlalchemy import (
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


class RegenerationPlanReplanRow(Base):
    __tablename__ = "regeneration_plan_replans"
    __table_args__ = (
        UniqueConstraint(
            "source_plan_id",
            name="uq_regeneration_replan_source",
        ),
        UniqueConstraint(
            "target_plan_id",
            name="uq_regeneration_replan_target",
        ),
        Index(
            "ix_regeneration_replans_project_created",
            "project_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_plan_id: Mapped[str] = mapped_column(
        ForeignKey("regeneration_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_plan_id: Mapped[str] = mapped_column(
        ForeignKey("regeneration_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )
    source_execution_attempt: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    target_snapshot_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
