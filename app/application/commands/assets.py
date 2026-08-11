"""Semantic asset commands."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.store import UnitOfWork
from app.store.repositories import NotFoundError

from .base import CommandValidationError, OperationExecution

MAX_UPLOAD_BYTES = 512 * 1024 * 1024


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


def _asset_snapshot(asset: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(asset)


def _require_unit_in_project(
    uow: UnitOfWork,
    project_id: str,
    unit_id: str | None,
) -> None:
    if not unit_id:
        return
    unit = uow.units.get(unit_id)
    if unit.project_id != project_id:
        raise NotFoundError(unit_id)


@dataclass(slots=True)
class CreateAssetCommand:
    project_id: str
    uri: str
    unit_id: str | None = None
    shot_id: str | None = None
    kind: str = "reference"
    name: str = ""
    mime_type: str = "application/octet-stream"
    sha256: str = ""
    parent_asset_id: str | None = None
    generation: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    operation_type = "asset.create"
    risk_level = "low"
    target_type = "project"

    @property
    def target_id(self) -> str:
        return self.project_id

    @property
    def idempotency_scope(self) -> str:
        return f"project:{self.project_id}"

    def arguments(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "shot_id": self.shot_id,
            "kind": self.kind,
            "name": self.name,
            "uri": self.uri,
            "mime_type": self.mime_type,
            "sha256": self.sha256,
            "parent_asset_id": self.parent_asset_id,
            **_fingerprint(self.generation, "generation"),
            **_fingerprint(self.metadata, "metadata"),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        conditions: list[dict[str, Any]] = [
            {"type": "project_exists", "id": self.project_id}
        ]
        if self.unit_id:
            conditions.append(
                {
                    "type": "unit_belongs_to_project",
                    "unit_id": self.unit_id,
                    "project_id": self.project_id,
                }
            )
        if self.parent_asset_id:
            conditions.append(
                {
                    "type": "asset_belongs_to_project",
                    "asset_id": self.parent_asset_id,
                    "project_id": self.project_id,
                }
            )
        return conditions

    def prepare(self, uow: UnitOfWork) -> None:
        uow.projects.get(self.project_id)
        if not str(self.uri or "").strip():
            raise CommandValidationError("asset uri cannot be empty")
        _require_unit_in_project(
            uow,
            self.project_id,
            self.unit_id,
        )
        if self.parent_asset_id:
            parent = uow.assets.get(self.parent_asset_id)
            if parent["project_id"] != self.project_id:
                raise NotFoundError(self.parent_asset_id)

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        asset = uow.assets.create(
            {
                "project_id": self.project_id,
                "unit_id": self.unit_id,
                "shot_id": self.shot_id,
                "kind": self.kind,
                "name": self.name,
                "uri": self.uri,
                "mime_type": self.mime_type,
                "sha256": self.sha256,
                "parent_asset_id": self.parent_asset_id,
                "generation": self.generation,
                "metadata": self.metadata,
            }
        )
        snapshot = _asset_snapshot(asset)
        return OperationExecution(
            result=snapshot,
            audit_result=snapshot,
            affected_entities=[
                {"type": "asset", "id": asset["id"]}
            ],
            inverse_operation={
                "type": "asset.delete_if_unreferenced",
                "asset_id": asset["id"],
            },
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return deepcopy(audit_result)


@dataclass(slots=True)
class CreateUploadedAssetCommand:
    project_id: str
    data: bytes = field(repr=False)
    filename: str
    media_store: Any = field(repr=False)
    unit_id: str | None = None
    kind: str = "reference"
    name: str = ""
    mime_type: str = "application/octet-stream"
    _operation_id: str | None = field(
        default=None,
        init=False,
        repr=False,
    )

    operation_type = "asset.upload"
    risk_level = "low"
    target_type = "project"

    @property
    def target_id(self) -> str:
        return self.project_id

    @property
    def idempotency_scope(self) -> str:
        return f"project:{self.project_id}:asset-upload"

    @property
    def suffix(self) -> str:
        return Path(self.filename or "").suffix.lower() or ".bin"

    def bind_operation_id(self, operation_id: str) -> None:
        self._operation_id = operation_id

    def arguments(self) -> dict[str, Any]:
        payload = bytes(self.data)
        return {
            "unit_id": self.unit_id,
            "kind": self.kind,
            "name": self.name,
            "filename": Path(self.filename or "upload").name,
            "suffix": self.suffix,
            "mime_type": self.mime_type,
            "content_sha256": hashlib.sha256(payload).hexdigest(),
            "content_bytes": len(payload),
        }

    def preconditions(self) -> list[dict[str, Any]]:
        conditions: list[dict[str, Any]] = [
            {"type": "project_exists", "id": self.project_id}
        ]
        if self.unit_id:
            conditions.append(
                {
                    "type": "unit_belongs_to_project",
                    "unit_id": self.unit_id,
                    "project_id": self.project_id,
                }
            )
        return conditions

    def prepare(self, uow: UnitOfWork) -> None:
        uow.projects.get(self.project_id)
        _require_unit_in_project(
            uow,
            self.project_id,
            self.unit_id,
        )
        if not isinstance(self.data, (bytes, bytearray)):
            raise CommandValidationError("upload content must be bytes")
        size = len(self.data)
        if size < 1:
            raise CommandValidationError("upload content cannot be empty")
        if size > MAX_UPLOAD_BYTES:
            raise CommandValidationError(
                f"upload cannot exceed {MAX_UPLOAD_BYTES} bytes"
            )

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        if not self._operation_id:
            raise RuntimeError("upload command is not bound to an operation id")
        uri = ""
        try:
            uri, sha256 = self.media_store.write_operation_bytes(
                self.project_id,
                bytes(self.data),
                self.suffix,
                self._operation_id,
                unit_id=self.unit_id,
            )
            metadata: dict[str, Any] = {}
            thumb_uri = uri if self.mime_type.startswith("image/") else ""
            try:
                metadata = self.media_store.probe(uri)
            except Exception:
                metadata = {}
            try:
                generated_thumb = self.media_store.make_thumb(
                    uri,
                    self.mime_type,
                )
                if generated_thumb:
                    thumb_uri = generated_thumb
            except Exception:
                pass

            asset = uow.assets.create(
                {
                    "project_id": self.project_id,
                    "unit_id": self.unit_id,
                    "kind": self.kind,
                    "name": (
                        self.name
                        or Path(self.filename or "upload").name
                    ),
                    "uri": uri,
                    "thumb_uri": thumb_uri,
                    "mime_type": self.mime_type,
                    "sha256": sha256,
                    "generation": {
                        "source": "upload",
                        "operation_id": self._operation_id,
                    },
                    "metadata": metadata,
                }
            )
        except Exception:
            if uri:
                self.media_store.delete_asset(uri)
            raise

        snapshot = _asset_snapshot(asset)
        return OperationExecution(
            result=snapshot,
            audit_result=snapshot,
            affected_entities=[
                {"type": "asset", "id": asset["id"]}
            ],
            # File-backed deletion/revert is introduced together with the
            # quarantine protocol; until then uploads remain audited but have
            # no falsely advertised inverse.
            inverse_operation=None,
            on_rollback=(
                lambda stored_uri=uri: self.media_store.delete_asset(
                    stored_uri
                )
            ),
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return deepcopy(audit_result)


@dataclass(slots=True)
class PatchAssetScopeCommand:
    asset_id: str
    unit_id: str | None = None
    shot_id: str | None = None
    set_unit_id: bool = False
    set_shot_id: bool = False
    project_id: str | None = None

    operation_type = "asset.scope.patch"
    risk_level = "medium"
    target_type = "asset"

    @property
    def target_id(self) -> str:
        return self.asset_id

    @property
    def idempotency_scope(self) -> str:
        return f"asset:{self.asset_id}"

    def arguments(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "set_unit_id": self.set_unit_id,
            "unit_id": self.unit_id if self.set_unit_id else None,
            "set_shot_id": self.set_shot_id,
            "shot_id": self.shot_id if self.set_shot_id else None,
        }

    def preconditions(self) -> list[dict[str, Any]]:
        return [{"type": "asset_exists", "id": self.asset_id}]

    def prepare(self, uow: UnitOfWork) -> None:
        asset = uow.assets.get(self.asset_id)
        self.project_id = asset["project_id"]
        if not self.set_unit_id and not self.set_shot_id:
            raise CommandValidationError(
                "asset patch must include unit_id or shot_id"
            )
        if self.set_unit_id:
            _require_unit_in_project(
                uow,
                asset["project_id"],
                self.unit_id,
            )

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        before = uow.assets.get(self.asset_id)
        kwargs: dict[str, Any] = {}
        if self.set_unit_id:
            kwargs["unit_id"] = self.unit_id
        if self.set_shot_id:
            kwargs["shot_id"] = self.shot_id
        saved = uow.assets.update_scope(
            self.asset_id,
            **kwargs,
        )
        snapshot = _asset_snapshot(saved)
        return OperationExecution(
            result=snapshot,
            audit_result=snapshot,
            affected_entities=[
                {"type": "asset", "id": self.asset_id}
            ],
            inverse_operation={
                "type": "asset.restore_scope",
                "asset_id": self.asset_id,
                "unit_id": before.get("unit_id"),
                "shot_id": before.get("shot_id"),
                "expected_unit_id": saved.get("unit_id"),
                "expected_shot_id": saved.get("shot_id"),
            },
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return deepcopy(audit_result)


__all__ = [
    "CreateAssetCommand",
    "CreateUploadedAssetCommand",
    "MAX_UPLOAD_BYTES",
    "PatchAssetScopeCommand",
]
