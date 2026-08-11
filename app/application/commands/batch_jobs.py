"""Atomic creation of a parent batch Job and its generated child Jobs."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from app.store import UnitOfWork
from app.store.repositories import NotFoundError

from .base import CommandValidationError, OperationExecution

MAX_BATCH_JOBS = 500


def _fingerprint(value: Any, prefix: str) -> dict[str, Any]:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        f"{prefix}_sha256": hashlib.sha256(encoded).hexdigest(),
        f"{prefix}_bytes": len(encoded),
    }


def _render_prompt(
    template: str,
    unit: dict[str, Any],
    style_direction: str,
) -> str:
    mapping = {
        "{unit.title}": unit.get("title", ""),
        "{unit.summary}": unit.get("summary", ""),
        "{bible.style.visual_direction}": style_direction,
    }
    result = template
    for key, value in mapping.items():
        result = result.replace(key, str(value or ""))
    return result


@dataclass(slots=True)
class CreateBatchJobsCommand:
    project_id: str
    unit_ids: list[str]
    capability: str = "image"
    prompt_template: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""

    operation_type = "job.batch.create"
    risk_level = "medium"
    target_type = "project"

    @property
    def target_id(self) -> str:
        return self.project_id

    @property
    def idempotency_scope(self) -> str:
        return f"project:{self.project_id}:batch-jobs"

    def arguments(self) -> dict[str, Any]:
        return {
            "unit_ids": list(self.unit_ids),
            "capability": self.capability,
            **_fingerprint(
                self.prompt_template,
                "prompt_template",
            ),
            **_fingerprint(self.params, "params"),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        return [
            {"type": "project_exists", "id": self.project_id},
            {
                "type": "units_belong_to_project",
                "unit_ids": list(self.unit_ids),
            },
        ]

    def prepare(self, uow: UnitOfWork) -> None:
        uow.projects.get(self.project_id)
        if not isinstance(self.params, dict):
            raise CommandValidationError(
                "batch params must be an object"
            )
        if not self.unit_ids:
            raise CommandValidationError(
                "batch generation requires at least one unit"
            )
        if len(self.unit_ids) > MAX_BATCH_JOBS:
            raise CommandValidationError(
                f"batch generation cannot exceed {MAX_BATCH_JOBS} units"
            )
        if len(set(self.unit_ids)) != len(self.unit_ids):
            raise CommandValidationError(
                "batch generation contains duplicate unit ids"
            )
        for unit_id in self.unit_ids:
            unit = uow.units.get(unit_id)
            if unit.project_id != self.project_id:
                raise NotFoundError(unit_id)

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        project = uow.projects.get(self.project_id)
        units = {
            unit.id: unit
            for unit in uow.units.list(self.project_id)
        }
        missing = [
            unit_id
            for unit_id in self.unit_ids
            if unit_id not in units
        ]
        if missing:
            raise NotFoundError(missing[0])

        parent = uow.jobs.create(
            {
                "project_id": self.project_id,
                "unit_id": None,
                "job_type": "batch",
                "payload": {"_request_id": self.request_id},
            }
        )
        children: list[dict[str, Any]] = []
        style_direction = project.bible.style.visual_direction
        for unit_id in self.unit_ids:
            unit = units[unit_id]
            prompt = _render_prompt(
                self.prompt_template,
                unit.model_dump(mode="json"),
                style_direction,
            )
            child = uow.jobs.create(
                {
                    "project_id": self.project_id,
                    "unit_id": unit_id,
                    "job_type": "media",
                    "parent_job_id": parent["id"],
                    "payload": {
                        "capability": self.capability,
                        "prompt": prompt,
                        "parameters": deepcopy(self.params),
                        "name": unit.title,
                        "_request_id": self.request_id,
                    },
                }
            )
            children.append(child)
        uow.jobs.update_payload(
            parent["id"],
            {
                "child_job_ids": [
                    child["id"] for child in children
                ],
                "child_count": len(children),
            },
        )
        parent = uow.jobs.get(parent["id"])
        result = {
            "parent_job_id": parent["id"],
            "child_job_ids": [
                child["id"] for child in children
            ],
        }
        return OperationExecution(
            result=result,
            audit_result=deepcopy(result),
            affected_entities=[
                {"type": "job", "id": parent["id"]},
                *[
                    {"type": "job", "id": child["id"]}
                    for child in children
                ],
            ],
            inverse_operation=None,
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return deepcopy(audit_result)


__all__ = ["CreateBatchJobsCommand", "MAX_BATCH_JOBS"]
