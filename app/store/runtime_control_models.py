"""Database rows for runtime admission and semantic event deduplication.

These mappings intentionally use a private registry instead of ``Base``.
Alembic owns their DDL, while historical ``Base.metadata.create_all`` fixtures
must continue to represent the pre-control-plane schema accurately.
"""

from sqlalchemy import Float, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, registry

runtime_control_registry = registry()


@runtime_control_registry.mapped
class RuntimeAdmissionBucketRow:
    """Configured capacity for one durable RuntimePlan kind."""

    __tablename__ = "runtime_admission_buckets"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


@runtime_control_registry.mapped
class RuntimeAdmissionReservationRow:
    """One durable Plan occupying one numbered capacity slot."""

    __tablename__ = "runtime_admission_reservations"
    __table_args__ = (
        Index(
            "ix_runtime_admission_reservations_bucket_release",
            "bucket_key",
            "released_at",
        ),
        Index(
            "uq_runtime_admission_active_slot",
            "bucket_key",
            "slot",
            unique=True,
            sqlite_where=text("released_at IS NULL"),
            postgresql_where=text("released_at IS NULL"),
        ),
    )

    plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    bucket_key: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        index=True,
    )
    slot: Mapped[int] = mapped_column(Integer, nullable=False)
    acquired_at: Mapped[float] = mapped_column(Float, nullable=False)
    released_at: Mapped[float | None] = mapped_column(Float, nullable=True)


@runtime_control_registry.mapped
class RuntimeEventDedupeRow:
    """Maps a semantic event identity to its first persisted RuntimeTaskEvent."""

    __tablename__ = "runtime_event_dedupes"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "dedupe_key",
            name="uq_runtime_event_dedupe_plan_key",
        ),
        Index(
            "ix_runtime_event_dedupes_event",
            "event_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    dedupe_key: Mapped[str] = mapped_column(String(240), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


__all__ = [
    "RuntimeAdmissionBucketRow",
    "RuntimeAdmissionReservationRow",
    "RuntimeEventDedupeRow",
    "runtime_control_registry",
]
