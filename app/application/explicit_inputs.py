"""Resolve explicit Artifact and Asset references into immutable Job inputs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.store.repositories import NotFoundError

from .commands.base import CommandValidationError

_ARTIFACT_TYPES = frozenset({"artifact", "artifact_current"})
_VERSION_TYPES = frozenset(
    {"artifact_version", "artifact-version", "version"}
)
_ASSET_TYPES = frozenset({"asset", "media_asset", "media-asset"})


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dumper = getattr(value, "model_dump", None)
    if dumper is not None:
        return dict(dumper(mode="json"))
    return {}


def _pinned_refs(project: Any) -> list[dict[str, Any]]:
    settings = getattr(project, "settings", None)
    data = _mapping(settings)
    refs = data.get("pinned_refs") or []
    return [
        normalized
        for ref in refs
        if (normalized := _mapping(ref))
    ]


def _turn_refs(uow, turn_id: str) -> list[dict[str, Any]]:
    turn = uow.agent_turns.get(turn_id)
    refs = turn.get("context_refs") or []
    return [
        normalized
        for ref in refs
        if (normalized := _mapping(ref))
    ]


def _append_unique(target: list[str], value: str) -> None:
    if value and value not in target:
        target.append(value)


def _require_artifact_project(
    uow,
    artifact_id: str,
    project_id: str,
) -> dict[str, Any]:
    artifact = uow.artifacts.get(artifact_id)
    if artifact["project_id"] != project_id:
        # Match the rest of the API boundary: do not reveal a foreign entity.
        raise NotFoundError(artifact_id)
    return artifact


def _require_version_project(
    uow,
    version_id: str,
    project_id: str,
) -> dict[str, Any]:
    version = uow.artifacts.get_version(version_id)
    _require_artifact_project(
        uow,
        str(version["artifact_id"]),
        project_id,
    )
    return version


def _require_asset_project(
    uow,
    asset_id: str,
    project_id: str,
) -> dict[str, Any]:
    asset = uow.assets.get(asset_id)
    if asset["project_id"] != project_id:
        raise NotFoundError(asset_id)
    return asset


def resolve_explicit_job_inputs(
    uow,
    project_id: str,
    turn_id: str,
    payload: Mapping[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    """Return exact version and Asset IDs for an Agent generation Job.

    Inputs come only from explicit request fields, the current Agent turn's
    ``context_refs`` and project ``pinned_refs``. Unit/project references are
    intentionally ignored: expanding them into every contained entity would
    create hidden dependencies and unstable idempotency semantics.
    """

    requested = dict(payload or {})
    version_ids: list[str] = []
    asset_ids: list[str] = []

    for version_id in requested.get("input_version_ids") or []:
        value = str(version_id or "")
        if not value:
            continue
        _require_version_project(uow, value, project_id)
        _append_unique(version_ids, value)

    for artifact_id in requested.get("input_artifact_ids") or []:
        value = str(artifact_id or "")
        if not value:
            continue
        artifact = _require_artifact_project(uow, value, project_id)
        current_version_id = str(
            artifact.get("current_version_id") or ""
        )
        if not current_version_id:
            raise CommandValidationError(
                f"explicit Artifact has no current version: {value}"
            )
        _append_unique(version_ids, current_version_id)

    for asset_id in requested.get("input_asset_ids") or []:
        value = str(asset_id or "")
        if not value:
            continue
        _require_asset_project(uow, value, project_id)
        _append_unique(asset_ids, value)

    project = uow.projects.get(project_id)
    refs: Iterable[dict[str, Any]] = [
        *_turn_refs(uow, turn_id),
        *_pinned_refs(project),
    ]
    for ref in refs:
        ref_type = str(ref.get("type") or "").strip().lower()
        ref_id = str(ref.get("id") or "").strip()
        if not ref_id:
            continue
        if ref_type in _ARTIFACT_TYPES:
            artifact = _require_artifact_project(
                uow,
                ref_id,
                project_id,
            )
            current_version_id = str(
                artifact.get("current_version_id") or ""
            )
            if not current_version_id:
                raise CommandValidationError(
                    f"explicit Artifact has no current version: {ref_id}"
                )
            _append_unique(version_ids, current_version_id)
        elif ref_type in _VERSION_TYPES:
            _require_version_project(uow, ref_id, project_id)
            _append_unique(version_ids, ref_id)
        elif ref_type in _ASSET_TYPES:
            _require_asset_project(uow, ref_id, project_id)
            _append_unique(asset_ids, ref_id)

    return version_ids, asset_ids


__all__ = ["resolve_explicit_job_inputs"]
