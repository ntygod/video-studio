"""Persist Provider response identity before the full response is durable."""

from __future__ import annotations

import time

from app.integrations.provider_request import current_provider_request
from app.store.repositories import ConflictError


def observe_provider_response(
    provider_request_id: str,
    provider_model_id: str = "",
) -> None:
    request_binding = current_provider_request()
    if request_binding is None:
        return
    request_id = str(provider_request_id or "").strip()[:300]
    if not request_id:
        return

    from app.application.runtime_governance import (
        current_runtime_execution,
    )
    from app.store import UnitOfWork

    runtime_binding = current_runtime_execution()
    if runtime_binding is None:
        return
    context = runtime_binding.context
    now = time.time()
    with UnitOfWork(context.runtime.database) as uow:
        uow.task_runtime._provider_request_lease(
            plan_id=context.plan["id"],
            task_id=context.task["id"],
            attempt_id=context.attempt["id"],
            claim_token=context.claim["claim_token"],
            now=now,
        )
        row = uow.task_runtime._provider_request_row(
            request_binding.request_id
        )
        if row.provider_request_id and row.provider_request_id != request_id:
            raise ConflictError(
                "Provider response request id changed during one dispatch"
            )
        row.provider_request_id = request_id
        row.updated_at = now
        if provider_model_id:
            summary = dict(row.request_summary_json and {})
            # The canonical model is already frozen on the request row. The
            # response model remains available in usage at normal completion.
            del summary
        uow.session.flush()


__all__ = ["observe_provider_response"]
