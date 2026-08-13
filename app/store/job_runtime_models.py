"""Partial ORM mapping for Runtime ownership columns on ``jobs``.

The historical JobRow mapper remains stable for legacy fixtures. This mapper
only owns the columns introduced after the generic Runtime tables existed.
"""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, registry

job_runtime_registry = registry()


@job_runtime_registry.mapped
class JobRuntimeLinkRow:
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    runtime_plan_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    runtime_task_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    runtime_generation: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )


__all__ = ["JobRuntimeLinkRow", "job_runtime_registry"]
