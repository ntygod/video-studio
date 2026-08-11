"""Persistence model for semantic operations and command audit."""

from sqlalchemy import Float, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class OperationLogRow(Base):
    __tablename__ = "operation_logs"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_operation_idempotency_key",
        ),
        Index(
            "ix_operation_project_created",
            "project_id",
            "created_at",
        ),
        Index(
            "ix_operation_status_created",
            "status",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    operation_type: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        index=True,
    )
    actor_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="user",
    )
    actor_id: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="local",
    )
    request_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
    )
    turn_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        index=True,
    )
    target_type: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="",
    )
    target_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="",
    )
    risk_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="low",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="running",
        index=True,
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    arguments_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    preconditions_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    affected_entities_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    inverse_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="null",
    )
    result_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="null",
    )
    error: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    completed_at: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    reverted_by_operation_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    reverted_at: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
