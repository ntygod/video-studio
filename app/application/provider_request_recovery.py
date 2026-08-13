"""Best-effort reconciliation loop for a bounded request batch."""

from __future__ import annotations

from app.application.provider_request_reconciliation import (
    observe_unknown_provider_request,
)
from app.application.provider_request_resolution import (
    save_provider_reconciliation,
)
from app.integrations.provider_reconciliation import (
    ProviderReconciliationConfigurationError,
    ProviderReconciliationError,
)
from app.store.repositories import NotFoundError


def reconcile_provider_requests(database, request_ids) -> int:
    changed = 0
    for request_id in list(request_ids)[:50]:
        try:
            _request, observation, _reason = (
                observe_unknown_provider_request(database, str(request_id))
            )
            if observation is None or observation.state not in {
                "completed",
                "failed",
            }:
                continue
            _saved, did_save, _note = save_provider_reconciliation(
                database,
                str(request_id),
                observation,
            )
            changed += int(did_save)
        except (
            ProviderReconciliationConfigurationError,
            ProviderReconciliationError,
            NotFoundError,
        ):
            continue
    return changed


__all__ = ["reconcile_provider_requests"]
