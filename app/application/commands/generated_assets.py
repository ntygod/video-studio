"""Durable persistence command for media-provider output bytes."""

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

MAX_GENERATED_MEDIA_BYTES = 1024 * 1024 * 1024


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


@dataclass(slots=True)
class PersistGeneratedAssetCommand:
    project_id: str
    data: bytes = field(repr=False)
    filename: str
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

    operation_type = "asset.generated.persist"
    risk_level = "low"
    target_type = "project"

    @property
    def target_id(self) -> str:
        return self.project_id

    @property
    def idempotency_scope(self) -> str:
        return f"project:{self.project_id}:generated-asset"

    @property
    def suffix(self) -> str:
        return Path(self.filename or "").suffix.lower() or ".bin"

    def bind_operation_id(self, operation_id: str) -> None:
        self._operation_id = operation_id

    def arguments(self) -> dict[str, Any]:
        content = bytes(self.data)
        return {
            "unit_id": self.unit_id,
            "kind": self.kind,
            "name": self.name,
            "filename": Path(self.filename or "generated.bin").name,
            "suffix": self.suffix,
            "mime_type": self.mime_type,
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "content_bytes": len(content),
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

    def prepare(self, uow: UnitOfWork) -> None:
        uow.projects.get(self.project_id)
        if self.unit_id:
            unit = uow.units.get(self.unit_id)
            if unit.project_id != self.project_id:
                raise NotFoundError(self.unit_id)
        if not isinstance(self.data, (bytes, bytearray)):
            raise CommandValidationError(
                "generated media content must be bytes"
            )
        size = len(self.data)
        if size < 1:
            raise CommandValidationError(
                "generated media content cannot be empty"
            )
        if size > MAX_GENERATED_MEDIA_BYTES:
            raise CommandValidationError(
                "generated media exceeds persistence limit"
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

            asset = uow.assets.create(
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
        except Exception:
            if uri:
                self.media_store.delete_asset(uri)
            raise

        snapshot = deepcopy(asset)
        return OperationExecution(
            result=snapshot,
            audit_result=snapshot,
            affected_entities=[
                {"type": "asset", "id": asset["id"]}
            ],
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


__all__ = [
    "MAX_GENERATED_MEDIA_BYTES",
    "PersistGeneratedAssetCommand",
]
