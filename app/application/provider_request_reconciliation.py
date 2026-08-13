"""Query one unknown Provider request without holding a DB transaction."""

from __future__ import annotations

from app.integrations.provider_reconciliation import (
    provider_reconciliation_supported,
    query_provider_request,
)
from app.store import UnitOfWork
from app.store.repositories import NotFoundError


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
    return request, observation, ""


__all__ = ["observe_unknown_provider_request"]
