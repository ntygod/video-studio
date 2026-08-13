"""Capture Provider response ids before full Agent response persistence."""

from __future__ import annotations

import time

from app.integrations.provider_response_identity import (
    clear_observed_provider_response,
    observed_provider_response,
)
from app.store import UnitOfWork
from app.store.repositories import ConflictError

from .runtime_cost_metering import MeteredLLMAdapter

_INSTALLED = False


def _capture(binding, request_id: str) -> None:
    observed = observed_provider_response(request_id)
    provider_request_id = str(
        observed.get("provider_request_id") or ""
    )[:300]
    if not provider_request_id:
        return
    context = binding.context
    now = time.time()
    with UnitOfWork(context.runtime.database) as uow:
        uow.task_runtime._provider_request_lease(
            plan_id=context.plan["id"],
            task_id=context.task["id"],
            attempt_id=context.attempt["id"],
            claim_token=context.claim["claim_token"],
            now=now,
        )
        row = uow.task_runtime._provider_request_row(request_id)
        if (
            row.provider_request_id
            and row.provider_request_id != provider_request_id
        ):
            raise ConflictError(
                "Provider response request id changed during one dispatch"
            )
        row.provider_request_id = provider_request_id
        row.updated_at = now
        uow.session.flush()


def install_provider_response_capture() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_started = MeteredLLMAdapter._mark_response_started
    original_failure = MeteredLLMAdapter._mark_failure
    original_record = MeteredLLMAdapter._record

    def captured_started(self, binding, request_id):
        _capture(binding, request_id)
        clear_observed_provider_response(request_id)
        return original_started(self, binding, request_id)

    def captured_failure(
        self,
        binding,
        request_id,
        exc,
        *,
        outcome_unknown,
    ):
        try:
            _capture(binding, request_id)
            return original_failure(
                self,
                binding,
                request_id,
                exc,
                outcome_unknown=outcome_unknown,
            )
        finally:
            clear_observed_provider_response(request_id)

    def captured_record(self, binding, request, usage, response):
        try:
            return original_record(self, binding, request, usage, response)
        finally:
            clear_observed_provider_response(str(request["id"]))

    MeteredLLMAdapter._mark_response_started = captured_started
    MeteredLLMAdapter._mark_failure = captured_failure
    MeteredLLMAdapter._record = captured_record


__all__ = ["install_provider_response_capture"]
