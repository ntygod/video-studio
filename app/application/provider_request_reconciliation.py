"""Query one unknown Provider request without holding a DB transaction."""

from __future__ import annotations

import time

from app.integrations.provider_reconciliation import (
    provider_reconciliation_supported,
    query_provider_request,
)
from app.store import UnitOfWork
from app.store.repositories import NotFoundError
from app.store.runtime_provider_request_models import (
    RuntimeProviderRequestRow,
)


def observe_unknown_provider_request(database, request_id: str):
    with UnitOfWork(database) as uow:
        request = uow.task_runtime.get_provider_request(request_id)
        if request["status"] != "outcome_unknown":
            return request, None, "request is no longer outcome_unknown"
        if not request.get("provider_request_id"):
            return request, None, "Provider request id is not available"
        try:
            provider = uow.providers.get(
                request["provider_profile_id"],
                include_secret=True,
            )
        except NotFoundError:
            return request, None, "Provider profile no longer exists"
    if not provider_reconciliation_supported(provider):
        return request, None, "Provider has no request_status_path"
    observation = query_provider_request(
        provider,
        str(request["provider_request_id"]),
    )
    with UnitOfWork(database) as uow:
        row = uow.session.get(RuntimeProviderRequestRow, request_id)
        if row is not None and row.status == "outcome_unknown":
            row.updated_at = time.time()
            uow.session.flush()
    return request, observation, ""


__all__ = ["observe_unknown_provider_request"]
