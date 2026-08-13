"""Durable identities and outcomes for external Provider requests."""

from sqlalchemy import Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .runtime_control_models import runtime_control_registry


@runtime_control_registry.mapped
class RuntimeProviderRequestRow:
    __tablename__ = "runtime_provider_requests"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "request_key",
            name="uq_runtime_provider_request_plan_key",
        ),
        Index(
            "ix_runtime_provider_requests_plan_created",
            "plan_id",
            "created_at",
        ),
        Index(
            "ix_runtime_provider_requests_status_updated",
            "status",
            "updated_at",
        ),
        Index(
            "ix_runtime_provider_requests_provider_id",
            "provider_request_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_key: Mapped[str] = mapped_column(String(240), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    provider_profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(200), nullable=False)
    adapter: Mapped[str] = mapped_column(String(100), nullable=False)
    model_profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(300), nullable=False)
    capability_type: Mapped[str] = mapped_column(String(50), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(240), nullable=False)
    idempotency_header: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_request_id: Mapped[str] = mapped_column(String(300), nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    usage_json: Mapped[str] = mapped_column(Text, nullable=False)
    cost_entry_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dispatch_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[str] = mapped_column(String(40), nullable=False)
    resolution_note: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_by_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resolved_by_id: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    dispatched_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    response_started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    completed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    failed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolved_at: Mapped[float | None] = mapped_column(Float, nullable=True)


__all__ = ["RuntimeProviderRequestRow"]
