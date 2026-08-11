"""Versioned definitions and validation for known Artifact kinds."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from pydantic import BaseModel, ValidationError

from .artifact_schemas import Screenplay
from .bible import ProjectBible
from .brief import CreativeBrief
from .narrative import StoryGraph
from .shot import ShotPlan
from .timeline import TimelineIR

MigrationHandler = Callable[[dict[str, Any]], dict[str, Any]]


class ArtifactSchemaError(ValueError):
    """A known Artifact payload or schema reference is invalid."""

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        schema_id: str = "",
        schema_version: int | None = None,
        errors: Iterable[dict[str, Any]] = (),
    ):
        super().__init__(message)
        self.kind = kind
        self.schema_id = schema_id
        self.schema_version = schema_version
        self.errors = list(errors)

    def detail(self) -> dict[str, Any]:
        return {
            "detail": str(self),
            "artifact_kind": self.kind,
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "errors": self.errors,
        }


@dataclass(frozen=True, slots=True)
class ArtifactDefinition:
    kind: str
    title: str
    schema_id: str
    schema_version: int
    model: type[BaseModel]
    aliases: tuple[str, ...] = ()
    legacy_schema_ids: tuple[str, ...] = ()
    migrations: Mapping[int, MigrationHandler] = field(default_factory=dict)

    @property
    def accepted_schema_ids(self) -> frozenset[str]:
        return frozenset((self.schema_id, *self.legacy_schema_ids))


@dataclass(frozen=True, slots=True)
class ValidatedArtifactPayload:
    payload: dict[str, Any]
    schema_id: str
    schema_version: int
    definition: ArtifactDefinition | None

    @property
    def known(self) -> bool:
        return self.definition is not None


def _validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for raw in exc.errors(include_url=False):
        item = dict(raw)
        if item.get("ctx"):
            item["ctx"] = {
                key: str(value) for key, value in item["ctx"].items()
            }
        errors.append(item)
    return errors


class ArtifactDefinitionRegistry:
    def __init__(self):
        self._by_kind: dict[str, ArtifactDefinition] = {}
        self._definitions: list[ArtifactDefinition] = []

    @staticmethod
    def _key(value: str) -> str:
        return (value or "").strip().lower()

    def register(self, definition: ArtifactDefinition) -> None:
        if definition.schema_version < 1:
            raise ValueError("schema_version must be >= 1")
        keys = (definition.kind, *definition.aliases)
        normalized = [self._key(value) for value in keys]
        if any(not value for value in normalized):
            raise ValueError("artifact kind and aliases cannot be empty")
        duplicates = [value for value in normalized if value in self._by_kind]
        if duplicates:
            raise ValueError(
                f"artifact definition already registered: {duplicates[0]}"
            )
        self._definitions.append(definition)
        for value in normalized:
            self._by_kind[value] = definition

    def resolve(self, kind: str) -> ArtifactDefinition | None:
        return self._by_kind.get(self._key(kind))

    def validate(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        schema_id: str | None = None,
        schema_version: int | None = None,
    ) -> ValidatedArtifactPayload:
        if not isinstance(payload, dict):
            raise ArtifactSchemaError(
                "Artifact payload 必须是 JSON 对象",
                kind=kind,
                schema_id=schema_id or "",
                schema_version=schema_version,
            )

        definition = self.resolve(kind)
        if definition is None:
            version = 1 if schema_version is None else int(schema_version)
            if version < 1:
                raise ArtifactSchemaError(
                    "schema_version 必须大于等于 1",
                    kind=kind,
                    schema_id=schema_id or "freeform",
                    schema_version=version,
                )
            return ValidatedArtifactPayload(
                payload=deepcopy(payload),
                schema_id=(schema_id or "freeform").strip() or "freeform",
                schema_version=version,
                definition=None,
            )

        requested_schema_id = (schema_id or "").strip()
        if (
            requested_schema_id
            and requested_schema_id != "freeform"
            and requested_schema_id not in definition.accepted_schema_ids
        ):
            raise ArtifactSchemaError(
                (
                    f"{kind} 不接受 schema_id={requested_schema_id}；"
                    f"应使用 {definition.schema_id}"
                ),
                kind=kind,
                schema_id=requested_schema_id,
                schema_version=schema_version,
            )

        source_version = (
            definition.schema_version
            if schema_version is None
            else int(schema_version)
        )
        if source_version < 1 or source_version > definition.schema_version:
            raise ArtifactSchemaError(
                (
                    f"{kind} 的 schema_version={source_version} 不受支持；"
                    f"当前版本为 {definition.schema_version}"
                ),
                kind=kind,
                schema_id=definition.schema_id,
                schema_version=source_version,
            )

        migrated = deepcopy(payload)
        current = source_version
        while current < definition.schema_version:
            migration = definition.migrations.get(current)
            if migration is None:
                raise ArtifactSchemaError(
                    (
                        f"{kind} 缺少 schema v{current} → "
                        f"v{current + 1} 的迁移处理器"
                    ),
                    kind=kind,
                    schema_id=definition.schema_id,
                    schema_version=current,
                )
            migrated = migration(deepcopy(migrated))
            if not isinstance(migrated, dict):
                raise ArtifactSchemaError(
                    "Artifact migration 必须返回 JSON 对象",
                    kind=kind,
                    schema_id=definition.schema_id,
                    schema_version=current,
                )
            current += 1

        try:
            model = definition.model.model_validate(migrated)
        except ValidationError as exc:
            raise ArtifactSchemaError(
                f"{kind} payload 不符合 {definition.schema_id}",
                kind=kind,
                schema_id=definition.schema_id,
                schema_version=definition.schema_version,
                errors=_validation_errors(exc),
            ) from exc

        return ValidatedArtifactPayload(
            payload=model.model_dump(mode="json"),
            schema_id=definition.schema_id,
            schema_version=definition.schema_version,
            definition=definition,
        )

    def describe(
        self,
        *,
        kind: str | None = None,
        include_schema: bool = True,
    ) -> list[dict[str, Any]]:
        definitions = (
            [self.resolve(kind)] if kind else list(self._definitions)
        )
        result: list[dict[str, Any]] = []
        for definition in definitions:
            if definition is None:
                continue
            item: dict[str, Any] = {
                "kind": definition.kind,
                "title": definition.title,
                "aliases": list(definition.aliases),
                "schema_id": definition.schema_id,
                "schema_version": definition.schema_version,
                "legacy_schema_ids": list(definition.legacy_schema_ids),
            }
            if include_schema:
                item["payload_schema"] = definition.model.model_json_schema()
            result.append(item)
        return result


def _default_registry() -> ArtifactDefinitionRegistry:
    registry = ArtifactDefinitionRegistry()
    registry.register(
        ArtifactDefinition(
            kind="brief",
            title="创作简报",
            schema_id="video-studio/brief@1",
            schema_version=1,
            model=CreativeBrief,
            legacy_schema_ids=("open/brief@1",),
        )
    )
    registry.register(
        ArtifactDefinition(
            kind="project_bible",
            title="项目设定",
            schema_id="video-studio/project-bible@1",
            schema_version=1,
            model=ProjectBible,
            legacy_schema_ids=("open/project_bible@1",),
        )
    )
    registry.register(
        ArtifactDefinition(
            kind="story_outline",
            title="故事结构",
            schema_id="video-studio/story-outline@1",
            schema_version=1,
            model=StoryGraph,
            aliases=("story_graph",),
            legacy_schema_ids=(
                "video-studio/story-graph@1",
                "open/story_graph@1",
                "open/story-outline@1",
            ),
        )
    )
    registry.register(
        ArtifactDefinition(
            kind="screenplay",
            title="剧本",
            schema_id="video-studio/screenplay@1",
            schema_version=1,
            model=Screenplay,
            legacy_schema_ids=("open/screenplay@1",),
        )
    )
    registry.register(
        ArtifactDefinition(
            kind="shot_plan",
            title="镜头方案",
            schema_id="video-studio/shot-plan@1",
            schema_version=1,
            model=ShotPlan,
            legacy_schema_ids=("open/shot_plan@1", "open/shot-plan@1"),
        )
    )
    registry.register(
        ArtifactDefinition(
            kind="timeline",
            title="时间线",
            schema_id="video-studio/timeline@1",
            schema_version=1,
            model=TimelineIR,
            legacy_schema_ids=("open/timeline@1",),
        )
    )
    return registry


artifact_definitions = _default_registry()


__all__ = [
    "ArtifactDefinition",
    "ArtifactDefinitionRegistry",
    "ArtifactSchemaError",
    "ValidatedArtifactPayload",
    "artifact_definitions",
]
