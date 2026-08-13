"""Resolve a Provider request from a terminal upstream observation."""

from __future__ import annotations

from app.store import UnitOfWork


def save_provider_reconciliation(
    database,
    request_id: str,
    observation,
    *,
    resolved_by_id: str = "provider-status-reconciler",
):
    if observation.state not in {"completed", "failed"}:
        raise ValueError("only terminal Provider observations can be saved")
    resolution = (
        "completed_external"
        if observation.state == "completed"
        else "failed_external"
    )
    note = (
        "Provider status query observed "
        f"{observation.status_value or observation.state}."
    )
    with UnitOfWork(database) as uow:
        current = uow.task_runtime.get_provider_request(request_id)
        if current["status"] != "outcome_unknown":
            return current, False, "request was resolved concurrently"
        saved = uow.task_runtime.resolve_provider_request(
            request_id,
            resolution=resolution,
            note=note,
            provider_request_id=observation.provider_request_id,
            resolved_by_type="runtime",
            resolved_by_id=resolved_by_id,
        )
    return saved, True, note


__all__ = ["save_provider_reconciliation"]
