"""Durable persistence commands for generated media Assets."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.store import UnitOfWork
from app.store.operation_models import OperationLogRow
from app.store.repositories import NotFoundError

from .base import CommandValidationError, OperationExecution

MAX_GENERATED_MEDIA_BYTES = 1024 * 1024 * 1024
ASSET_PERSIST_OPERATION_TYPES = frozenset(
    {"asset.generated.persist", "asset.generated-file.persist"}
)


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


def job_asset_persistence_attempt(
    database,
    job_id: str,
) -> tuple[dict[str, Any] | None, str]:
    """Reuse any successful Asset output before another expensive generation."""

    with UnitOfWork(database) as uow:
        rows = uow.session.scalars(
            select(OperationLogRow)
            .where(
                OperationLogRow.operation_type.in_(
                    ASSET_PERSIST_OPERATION_TYPES
                ),
                OperationLogRow.actor_type == "job",
                OperationLogRow.actor_id == job_id,
            )
            .order_by(
                OperationLogRow.created_at,
                OperationLogRow.id,
            )
        ).all()
        for row in rows:
            if row.status != "succeeded":
                continue
            operation = uow.operations.get(row.id)
            snapshot = deepcopy(operation.get("result") or {})
            asset_id = str(snapshot.get("id") or "")
            if not asset_id:
                continue
            try:
                uow.assets.get(asset_id)
            except Exception:
                continue
            return snapshot, str(row.idempotency_key or "")
        running = next(
            (row for row in reversed(rows) if row.status == "running"),
            None,
        )
        if running is not None and running.idempotency_key:
            return None, str(running.idempotency_key)
        return None, f"job:{job_id}:asset:{len(rows) + 1}"


@dataclass(slots=True)
class _GeneratedAssetBase:
    project_id: str
    media_store: Any = field(repr=False)
    unit_id: str | None = None
    kind: str = "image"
    name: str = "AI 生成"
    mime_type: str = "application/octet-stream"
    generation: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    _operation_id: str | None = field(
        default=None,
        init=False,
        repr=False,
    )

    risk_level = "low"
    target_type = "project"

    @property
    def target_id(self) -> str:
        return self.project_id

    @property
    def idempotency_scope(self) -> str:
        return f"project:{self.project_id}:generated-asset"

    def bind_operation_id(self, operation_id: str) -> None:
        self._operation_id = operation_id

    def _base_arguments(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "kind": self.kind,
            "name": self.name,
            "mime_type": self.mime_type,
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
        return conditions

    def _prepare_scope(self, uow: UnitOfWork) -> None:
        uow.projects.get(self.project_id)
        if self.unit_id:
            unit = uow.units.get(self.unit_id)
            if unit.project_id != self.project_id:
                raise NotFoundError(self.unit_id)

    def _create_asset(
        self,
        uow: UnitOfWork,
        uri: str,
        sha256: str,
    ) -> dict[str, Any]:
        probed: dict[str, Any] = {}
        thumb_uri = uri if self.mime_type.startswith("image/") else ""
        try:
            probed = self.media_store.probe(uri)
        except Exception:
            probed = {}
        try:
            generated_thumb = self.media_store.make_thumb(
                uri,
                self.mime_type,
            )
            if generated_thumb:
                thumb_uri = generated_thumb
        except Exception:
            pass
        return uow.assets.create(
            {
                "project_id": self.project_id,
                "unit_id": self.unit_id,
                "kind": self.kind,
                "name": self.name,
                "uri": uri,
                "thumb_uri": thumb_uri,
                "mime_type": self.mime_type,
                "sha256": sha256,
                "generation": {
                    **deepcopy(self.generation),
                    "operation_id": self._operation_id,
                },
                "metadata": {
                    **deepcopy(self.metadata),
                    **probed,
                },
            }
        )

    @staticmethod
    def _execution(
        asset: dict[str, Any],
        cleanup,
    ) -> OperationExecution:
        snapshot = deepcopy(asset)
        return OperationExecution(
            result=snapshot,
            audit_result=snapshot,
            affected_entities=[
                {"type": "asset", "id": asset["id"]}
            ],
            inverse_operation=None,
            on_rollback=cleanup,
        )

    def replay(
        self,
        uow: UnitOfWork,
        audit_result: Any,
    ) -> dict[str, Any]:
        return deepcopy(audit_result)


@dataclass(slots=True)
class PersistGeneratedAssetCommand(_GeneratedAssetBase):
    data: bytes = field(default=b"", repr=False)
    filename: str = "generated.bin"

    operation_type = "asset.generated.persist"

    @property
    def suffix(self) -> str:
        return Path(self.filename or "").suffix.lower() or ".bin"

    def arguments(self) -> dict[str, Any]:
        content = bytes(self.data)
        return {
            **self._base_arguments(),
            "filename": Path(self.filename or "generated.bin").name,
            "suffix": self.suffix,
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "content_bytes": len(content),
        }

    def prepare(self, uow: UnitOfWork) -> None:
        self._prepare_scope(uow)
        if not isinstance(self.data, (bytes, bytearray)):
            raise CommandValidationError(
                "generated media content must be bytes"
            )
        if not 0 < len(self.data) <= MAX_GENERATED_MEDIA_BYTES:
            raise CommandValidationError(
                "generated media content has an invalid size"
            )

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        if not self._operation_id:
            raise RuntimeError(
                "generated asset command is not bound to an operation id"
            )
        uri = ""
        try:
            uri, sha256 = self.media_store.write_operation_bytes(
                self.project_id,
                bytes(self.data),
                self.suffix,
                self._operation_id,
                unit_id=self.unit_id,
            )
            asset = self._create_asset(uow, uri, sha256)
        except Exception:
            if uri:
                self.media_store.delete_asset(uri)
            raise
        return self._execution(
            asset,
            lambda stored_uri=uri: self.media_store.delete_asset(
                stored_uri
            ),
        )


@dataclass(slots=True)
class PersistGeneratedFileAssetCommand(_GeneratedAssetBase):
    source_uri: str = ""

    operation_type = "asset.generated-file.persist"

    def arguments(self) -> dict[str, Any]:
        source = self.media_store.path_for(self.source_uri)
        return {
            **self._base_arguments(),
            "source_suffix": source.suffix.lower(),
            "source_bytes": source.stat().st_size if source.exists() else None,
        }

    def prepare(self, uow: UnitOfWork) -> None:
        self._prepare_scope(uow)
        source = self.media_store.path_for(self.source_uri)
        if not source.is_file():
            raise CommandValidationError(
                "generated media source file does not exist"
            )

    def execute(self, uow: UnitOfWork) -> OperationExecution:
        if not self._operation_id:
            raise RuntimeError(
                "generated file command is not bound to an operation id"
            )
        uri = ""
        try:
            uri, sha256 = self.media_store.adopt_operation_file(
                self.project_id,
                self.source_uri,
                self._operation_id,
                unit_id=self.unit_id,
            )
            asset = self._create_asset(uow, uri, sha256)
        except Exception:
            if uri:
                self.media_store.delete_asset(uri)
            raise
        return self._execution(
            asset,
            lambda stored_uri=uri: self.media_store.delete_asset(
                stored_uri
            ),
        )


__all__ = [
    "ASSET_PERSIST_OPERATION_TYPES",
    "MAX_GENERATED_MEDIA_BYTES",
    "PersistGeneratedAssetCommand",
    "PersistGeneratedFileAssetCommand",
    "job_asset_persistence_attempt",
]
