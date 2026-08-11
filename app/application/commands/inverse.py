"""Safe execution of persisted inverse operations."""

from __future__ import annotations

from copy import deepcopy
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, exists, func, select, update

from app.domain import CreativeProject, CreativeUnit
from app.domain.enums import ProposalStatus
from app.store import UnitOfWork
from app.store.models import (
    ArtifactRow,
    ArtifactVersionRow,
    AssetRow,
    ConversationRow,
    CreativeUnitRow,
    JobRow,
    ProjectRow,
    ProposalRow,
)
from app.store.json_codec import dumps
from app.store.repositories import ConflictError

from .base import CommandValidationError, OperationExecution
from .projects import _validate_parent_change


@dataclass(frozen=True, slots=True)
class AppliedInverse:
    result: dict[str, Any]
    affected_entities: list[dict[str, Any]]


def _has_rows(
    uow: UnitOfWork,
    model,
    *conditions,
) -> bool:
    count = uow.session.scalar(
        select(func.count())
        .select_from(model)
        .where(*conditions)
    )
    return bool(count)


def _delete_artifact_if_pristine(
    uow: UnitOfWork,
    inverse: dict[str, Any],
) -> AppliedInverse:
    artifact_id = str(inverse.get("artifact_id") or "")
    version_id = str(inverse.get("version_id") or "")
    artifact = uow.session.get(ArtifactRow, artifact_id)
    if artifact is None:
        return AppliedInverse(
            result={
                "type": inverse["type"],
                "artifact_id": artifact_id,
                "already_missing": True,
            },
            affected_entities=[],
        )
    versions = uow.session.scalars(
        select(ArtifactVersionRow)
        .where(ArtifactVersionRow.artifact_id == artifact_id)
        .order_by(ArtifactVersionRow.version)
    ).all()
    if (
        len(versions) != 1
        or versions[0].id != version_id
        or artifact.current_version_id != version_id
    ):
        raise ConflictError(
            "artifact is no longer the pristine created version"
        )
    if versions[0].status != "draft":
        raise ConflictError(
            "approved or locked artifact cannot be deleted by revert"
        )

    version_count = (
        select(func.count())
        .select_from(ArtifactVersionRow)
        .where(ArtifactVersionRow.artifact_id == artifact_id)
        .scalar_subquery()
    )
    draft_version_exists = exists(
        select(1).where(
            ArtifactVersionRow.id == version_id,
            ArtifactVersionRow.artifact_id == artifact_id,
            ArtifactVersionRow.status == "draft",
        )
    )
    proposal_exists = exists(
        select(1).where(
            ProposalRow.artifact_id == artifact_id
        )
    )
    deleted = uow.session.execute(
        delete(ArtifactRow)
        .where(
            ArtifactRow.id == artifact_id,
            ArtifactRow.current_version_id == version_id,
            ArtifactRow.revision == artifact.revision,
            version_count == 1,
            draft_version_exists,
            ~proposal_exists,
        )
        .execution_options(synchronize_session=False)
    )
    if deleted.rowcount != 1:
        raise ConflictError(
            "artifact changed while the revert was being applied"
        )
    uow.session.flush()
    return AppliedInverse(
        result={
            "type": inverse["type"],
            "artifact_id": artifact_id,
            "deleted": True,
        },
        affected_entities=[
            {"type": "artifact", "id": artifact_id}
        ],
    )


def _restore_artifact_version(
    uow: UnitOfWork,
    inverse: dict[str, Any],
) -> AppliedInverse:
    artifact_id = str(inverse.get("artifact_id") or "")
    previous_version_id = str(
        inverse.get("version_id") or ""
    )
    created_version_id = str(
        inverse.get("created_version_id") or ""
    )
    artifact = uow.artifacts.get(artifact_id)
    if artifact.get("current_version_id") != created_version_id:
        raise ConflictError(
            "artifact has a later version and cannot be reverted"
        )
    if not previous_version_id:
        raise CommandValidationError(
            "artifact restore inverse has no previous version"
        )
    previous = uow.artifacts.get_version(
        previous_version_id
    )
    if previous["artifact_id"] != artifact_id:
        raise ConflictError(
            "previous version belongs to another artifact"
        )
    restored = uow.artifacts.add_version(
        artifact_id,
        previous["payload"],
        source="system",
        note=(
            "Operation revert restored "
            f"v{previous['version']}"
        ),
        schema_version=previous.get("schema_version"),
        parent_version_id=created_version_id,
    )
    return AppliedInverse(
        result={
            "type": inverse["type"],
            "artifact_id": artifact_id,
            "restored_from_version_id": previous_version_id,
            "created_version_id": restored["id"],
        },
        affected_entities=[
            {"type": "artifact", "id": artifact_id},
            {
                "type": "artifact_version",
                "id": restored["id"],
            },
        ],
    )


def _reject_proposal_if_pending(
    uow: UnitOfWork,
    inverse: dict[str, Any],
) -> AppliedInverse:
    proposal_id = str(inverse.get("proposal_id") or "")
    proposal = uow.proposals.get(proposal_id)
    if proposal["status"] == ProposalStatus.ACCEPTED.value:
        raise ConflictError(
            "accepted proposal cannot be reverted by rejection"
        )
    if proposal["status"] == ProposalStatus.PENDING.value:
        changed = uow.session.execute(
            update(ProposalRow)
            .where(
                ProposalRow.id == proposal_id,
                ProposalRow.status
                == ProposalStatus.PENDING.value,
            )
            .values(
                status=ProposalStatus.REJECTED.value,
                updated_at=time.time(),
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            uow.session.expire_all()
            current = uow.proposals.get(proposal_id)
            if (
                current["status"]
                != ProposalStatus.REJECTED.value
            ):
                raise ConflictError(
                    "proposal changed while the revert was being applied"
                )
        uow.session.expire_all()
        proposal = uow.proposals.get(proposal_id)
    return AppliedInverse(
        result={
            "type": inverse["type"],
            "proposal": proposal,
        },
        affected_entities=[
            {"type": "proposal", "id": proposal_id}
        ],
    )


def _restore_unit_snapshot(
    uow: UnitOfWork,
    inverse: dict[str, Any],
) -> AppliedInverse:
    snapshot = deepcopy(inverse.get("unit") or {})
    unit_id = str(snapshot.get("id") or "")
    if not unit_id:
        raise CommandValidationError(
            "unit restore inverse has no unit id"
        )
    expected = inverse.get("expected_updated_at")
    if expected is None:
        raise CommandValidationError(
            "unit restore inverse has no expected_updated_at"
        )
    restored = CreativeUnit.model_validate(snapshot)
    current = uow.units.get(unit_id)
    if restored.project_id != current.project_id:
        raise ConflictError(
            "unit snapshot belongs to another project"
        )
    _validate_parent_change(
        uow,
        current.project_id,
        unit_id,
        restored.parent_id,
    )
    updated_at = time.time()
    changed = uow.session.execute(
        update(CreativeUnitRow)
        .where(
            CreativeUnitRow.id == unit_id,
            CreativeUnitRow.project_id == restored.project_id,
            CreativeUnitRow.updated_at == float(expected),
        )
        .values(
            parent_id=restored.parent_id,
            unit_type=restored.unit_type,
            order_index=restored.order_index,
            title=restored.title,
            summary=restored.summary,
            stage=restored.stage,
            continuity_summary=restored.continuity_summary,
            custom_json=dumps(restored.custom_fields),
            updated_at=updated_at,
        )
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        raise ConflictError(
            "unit changed while the revert was being applied"
        )
    uow.session.expire_all()
    saved = uow.units.get(unit_id)
    return AppliedInverse(
        result={
            "type": inverse["type"],
            "unit": saved.model_dump(mode="json"),
        },
        affected_entities=[
            {"type": "unit", "id": unit_id}
        ],
    )


def _unit_depth(
    row: CreativeUnitRow,
    rows: dict[str, CreativeUnitRow],
) -> int:
    depth = 0
    parent_id = row.parent_id
    seen: set[str] = set()
    while parent_id and parent_id in rows:
        if parent_id in seen:
            raise ConflictError(
                "unit batch contains a parent cycle"
            )
        seen.add(parent_id)
        depth += 1
        parent_id = rows[parent_id].parent_id
    return depth


def _delete_units_if_pristine(
    uow: UnitOfWork,
    inverse: dict[str, Any],
) -> AppliedInverse:
    unit_ids = [
        str(item)
        for item in inverse.get("unit_ids") or []
        if str(item)
    ]
    if not unit_ids:
        raise CommandValidationError(
            "unit delete inverse has no unit ids"
        )
    project_id = str(inverse.get("project_id") or "")
    if not project_id:
        raise CommandValidationError(
            "unit delete inverse has no project id"
        )
    rows = {
        row.id: row
        for row in uow.session.scalars(
            select(CreativeUnitRow).where(
                CreativeUnitRow.id.in_(unit_ids)
            )
        ).all()
    }
    foreign_rows = [
        row.id
        for row in rows.values()
        if row.project_id != project_id
    ]
    if foreign_rows:
        raise ConflictError(
            "unit delete inverse contains foreign project units"
        )
    ordered = sorted(
        rows.values(),
        key=lambda row: _unit_depth(row, rows),
        reverse=True,
    )
    deleted_ids: list[str] = []
    for row in ordered:
        child_exists = exists(
            select(1).where(
                CreativeUnitRow.parent_id == row.id
            )
        )
        blockers = (
            exists(
                select(1).where(
                    ArtifactRow.unit_id == row.id
                )
            ),
            exists(
                select(1).where(AssetRow.unit_id == row.id)
            ),
            exists(
                select(1).where(JobRow.unit_id == row.id)
            ),
            exists(
                select(1).where(
                    ConversationRow.unit_id == row.id
                )
            ),
            exists(
                select(1).where(
                    ProposalRow.unit_id == row.id
                )
            ),
        )
        statement = delete(CreativeUnitRow).where(
            CreativeUnitRow.id == row.id,
            CreativeUnitRow.project_id == project_id,
            CreativeUnitRow.created_at == row.created_at,
            CreativeUnitRow.updated_at
            <= row.created_at + 0.001,
            ~child_exists,
            *[~blocker for blocker in blockers],
        )
        removed = uow.session.execute(
            statement.execution_options(
                synchronize_session=False
            )
        )
        if removed.rowcount != 1:
            raise ConflictError(
                f"unit {row.id} changed or gained references"
            )
        deleted_ids.append(row.id)
    uow.session.flush()
    return AppliedInverse(
        result={
            "type": inverse["type"],
            "deleted_unit_ids": deleted_ids,
            "already_missing_unit_ids": [
                unit_id
                for unit_id in unit_ids
                if unit_id not in rows
            ],
        },
        affected_entities=[
            {"type": "unit", "id": unit_id}
            for unit_id in deleted_ids
        ],
    )


def _restore_project_snapshot(
    uow: UnitOfWork,
    inverse: dict[str, Any],
) -> AppliedInverse:
    snapshot = deepcopy(inverse.get("project") or {})
    project_id = str(snapshot.get("id") or "")
    if not project_id:
        raise CommandValidationError(
            "project restore inverse has no project id"
        )
    expected = inverse.get("expected_revision")
    if expected is None:
        raise CommandValidationError(
            "project restore inverse has no expected_revision"
        )
    restored = CreativeProject.model_validate(snapshot)
    if restored.id != project_id:
        raise ConflictError(
            "project snapshot id does not match its target"
        )

    tracked_kinds = {"brief", "project_bible"}
    before_artifacts = {
        item["kind"]: {
            "artifact_id": item["id"],
            "version_id": (
                (item.get("current_version") or {}).get("id")
            ),
            "payload": (
                (item.get("current_version") or {}).get("payload")
            ),
        }
        for item in uow.artifacts.list(
            project_id,
            unit_id=None,
            include_payload=True,
        )
        if item["kind"] in tracked_kinds
    }

    updated_at = time.time()
    changed = uow.session.execute(
        update(ProjectRow)
        .where(
            ProjectRow.id == project_id,
            ProjectRow.revision == int(expected),
        )
        .values(
            title=restored.title,
            project_type=restored.project_type,
            workflow_id=restored.workflow_id,
            stage=restored.stage,
            brief_json=dumps(
                restored.brief.model_dump(mode="json")
            ),
            bible_json=dumps(
                restored.bible.model_dump(mode="json")
            ),
            settings_json=dumps(
                restored.settings.model_dump(mode="json")
            ),
            custom_json=dumps(restored.custom_fields),
            revision=int(expected) + 1,
            updated_at=updated_at,
        )
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        raise ConflictError(
            "project changed while the revert was being applied"
        )
    uow.session.expire_all()
    saved = uow.projects.get(project_id)

    payloads = {
        "brief": (
            "创作 Brief",
            "video-studio/brief@1",
            saved.brief.model_dump(mode="json"),
        ),
        "project_bible": (
            "项目 Bible",
            "video-studio/project-bible@1",
            saved.bible.model_dump(mode="json"),
        ),
    }
    for kind, (name, schema_id, payload) in payloads.items():
        previous = before_artifacts.get(kind)
        if previous is None:
            uow.artifacts.create(
                project_id=project_id,
                unit_id=None,
                kind=kind,
                name=name,
                schema_id=schema_id,
                payload=payload,
                source="system",
            )
            continue
        if previous.get("payload") != payload:
            uow.artifacts.add_version(
                previous["artifact_id"],
                payload,
                source="system",
                note="Operation revert restored project state",
                parent_version_id=previous.get("version_id"),
            )

    affected_entities = [
        {"type": "project", "id": project_id}
    ]
    for item in uow.artifacts.list(
        project_id,
        unit_id=None,
        include_payload=False,
    ):
        if item["kind"] not in tracked_kinds:
            continue
        version_id = (
            (item.get("current_version") or {}).get("id")
        )
        previous = before_artifacts.get(item["kind"]) or {}
        if (
            previous.get("artifact_id") == item["id"]
            and previous.get("version_id") == version_id
        ):
            continue
        affected_entities.append(
            {"type": "artifact", "id": item["id"]}
        )
        if version_id:
            affected_entities.append(
                {
                    "type": "artifact_version",
                    "id": version_id,
                }
            )

    return AppliedInverse(
        result={
            "type": inverse["type"],
            "project": saved.model_dump(mode="json"),
        },
        affected_entities=affected_entities,
    )


def _restore_asset_scope(
    uow: UnitOfWork,
    inverse: dict[str, Any],
) -> AppliedInverse:
    asset_id = str(inverse.get("asset_id") or "")
    asset = uow.assets.get(asset_id)
    expected_unit_id = inverse.get("expected_unit_id")
    expected_shot_id = inverse.get("expected_shot_id")
    unit_id = inverse.get("unit_id")
    shot_id = inverse.get("shot_id")
    if unit_id:
        unit = uow.units.get(str(unit_id))
        if unit.project_id != asset["project_id"]:
            raise ConflictError(
                "asset inverse points to a foreign unit"
            )

    unit_condition = (
        AssetRow.unit_id.is_(None)
        if expected_unit_id is None
        else AssetRow.unit_id == expected_unit_id
    )
    shot_condition = (
        AssetRow.shot_id.is_(None)
        if expected_shot_id is None
        else AssetRow.shot_id == expected_shot_id
    )
    changed = uow.session.execute(
        update(AssetRow)
        .where(
            AssetRow.id == asset_id,
            unit_condition,
            shot_condition,
        )
        .values(
            unit_id=unit_id or None,
            shot_id=shot_id or None,
        )
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        raise ConflictError(
            "asset scope changed while the revert was being applied"
        )
    uow.session.expire_all()
    saved = uow.assets.get(asset_id)
    return AppliedInverse(
        result={
            "type": inverse["type"],
            "asset": saved,
        },
        affected_entities=[
            {"type": "asset", "id": asset_id}
        ],
    )


def _cancel_queued_job(
    uow: UnitOfWork,
    inverse: dict[str, Any],
) -> AppliedInverse:
    job_id = str(inverse.get("job_id") or "")
    job = uow.jobs.get(job_id)
    transitioned = False
    if job["status"] == "queued":
        changed = uow.session.execute(
            update(JobRow)
            .where(
                JobRow.id == job_id,
                JobRow.status == "queued",
            )
            .values(
                status="canceled",
                cancel_requested=True,
                worker_id="",
                lease_until=None,
                updated_at=time.time(),
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount == 1:
            transitioned = True
        else:
            uow.session.expire_all()
            job = uow.jobs.get(job_id)
    if not transitioned and job["status"] != "canceled":
        raise ConflictError(
            "only a still-queued job can be reverted safely"
        )
    if transitioned:
        uow.jobs.add_event(
            job_id,
            "Operation revert canceled queued job",
            level="warning",
            stage="revert",
        )
        uow.session.expire_all()
        job = uow.jobs.get(job_id)
    return AppliedInverse(
        result={
            "type": inverse["type"],
            "job_id": job_id,
            "status": job["status"],
        },
        affected_entities=[
            {"type": "job", "id": job_id}
        ],
    )


HANDLERS = {
    "artifact.delete_if_pristine": _delete_artifact_if_pristine,
    "artifact.restore_version": _restore_artifact_version,
    "proposal.reject_if_pending": _reject_proposal_if_pending,
    "unit.restore_snapshot": _restore_unit_snapshot,
    "unit.delete_many_if_pristine": _delete_units_if_pristine,
    "project.restore_snapshot": _restore_project_snapshot,
    "asset.restore_scope": _restore_asset_scope,
    "job.cancel": _cancel_queued_job,
}


def apply_inverse_operation(
    uow: UnitOfWork,
    inverse: dict[str, Any],
) -> AppliedInverse:
    inverse_type = str(inverse.get("type") or "")
    handler = HANDLERS.get(inverse_type)
    if handler is None:
        raise CommandValidationError(
            f"inverse operation is not supported: {inverse_type}"
        )
    return handler(uow, inverse)


@dataclass(slots=True)
class RevertOperationCommand:
    operation_id: str
    project_id: str | None = None
    _revert_operation_id: str | None = field(
        default=None,
        init=False,
        repr=False,
    )

    operation_type = "operation.revert"
    risk_level = "high"
    target_type = "operation"

    @property
    def target_id(self) -> str:
        return self.operation_id

    @property
    def idempotency_scope(self) -> str:
        return f"operation:{self.operation_id}"

    def arguments(self) -> dict[str, Any]:
        return {"operation_id": self.operation_id}

    def preconditions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "operation_status_is",
                "status": "succeeded",
            },
            {"type": "operation_is_not_reverted"},
            {"type": "inverse_operation_is_supported"},
        ]

    def bind_operation_id(
        self,
        operation_id: str,
    ) -> None:
        self._revert_operation_id = operation_id

    def prepare(self, uow: UnitOfWork) -> None:
        original = uow.operations.get(self.operation_id)
        self.project_id = original.get("project_id")
        if original["status"] != "succeeded":
            raise ConflictError(
                "only succeeded operations can be reverted"
            )
        if original.get("reverted_by_operation_id"):
            raise ConflictError(
                "operation has already been reverted"
            )
        inverse = original.get("inverse_operation")
        if not isinstance(inverse, dict):
            raise CommandValidationError(
                "operation has no executable inverse"
            )
        inverse_type = str(inverse.get("type") or "")
        if inverse_type not in HANDLERS:
            raise CommandValidationError(
                f"inverse operation is not supported: {inverse_type}"
            )

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        if not self._revert_operation_id:
            raise RuntimeError(
                "revert command is not bound to an operation id"
            )
        original = uow.operations.get(self.operation_id)
        if original.get("reverted_by_operation_id"):
            raise ConflictError(
                "operation has already been reverted"
            )
        inverse = original.get("inverse_operation")
        if not isinstance(inverse, dict):
            raise CommandValidationError(
                "operation has no executable inverse"
            )
        applied = apply_inverse_operation(uow, inverse)
        original = uow.operations.mark_reverted(
            self.operation_id,
            self._revert_operation_id,
        )
        result = {
            "operation": original,
            "compensation": applied.result,
        }
        return OperationExecution(
            result=result,
            audit_result={
                "original_operation_id": self.operation_id,
                "compensation": applied.result,
            },
            affected_entities=[
                {
                    "type": "operation",
                    "id": self.operation_id,
                },
                *applied.affected_entities,
            ],
            inverse_operation=None,
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        stored = audit_result or {}
        return {
            "operation": uow.operations.get(
                str(stored["original_operation_id"])
            ),
            "compensation": deepcopy(
                stored.get("compensation") or {}
            ),
        }


__all__ = [
    "AppliedInverse",
    "HANDLERS",
    "RevertOperationCommand",
    "apply_inverse_operation",
]
