import time
import uuid
from typing import Any

from app.domain import (
    CreativeBrief,
    CreativeProject,
    CreativeUnit,
    ProjectBible,
    ProjectSettings,
)


def create_project(
    uow,
    *,
    title: str,
    project_id: str | None = None,
    project_type: str = "freeform",
    workflow_id: str = "freeform",
    concept: str = "",
    format_id: str = "freeform",
    custom_fields: dict[str, Any] | None = None,
) -> CreativeProject:
    now = time.time()
    project = CreativeProject(
        id=project_id or uuid.uuid4().hex,
        title=title.strip() or "未命名项目",
        project_type=project_type or "freeform",
        workflow_id=workflow_id or "freeform",
        stage="brief",
        brief=CreativeBrief(
            title=title.strip() or "未命名项目",
            concept=concept,
            format_id=format_id or "freeform",
        ),
        bible=ProjectBible(),
        settings=ProjectSettings(),
        custom_fields=custom_fields or {},
        revision=1,
        created_at=now,
        updated_at=now,
    )
    created = uow.projects.create(project)
    uow.artifacts.create(
        project_id=created.id,
        unit_id=None,
        kind="brief",
        name="创作 Brief",
        schema_id="video-studio/brief@1",
        payload=created.brief.model_dump(mode="json"),
        source="system",
    )
    uow.artifacts.create(
        project_id=created.id,
        unit_id=None,
        kind="project_bible",
        name="项目 Bible",
        schema_id="video-studio/project-bible@1",
        payload=created.bible.model_dump(mode="json"),
        source="system",
    )
    return created


def patch_project(
    uow,
    project_id: str,
    patch: dict[str, Any],
    expected_revision: int,
):
    project = uow.projects.get(project_id)
    data = project.model_dump(mode="json")
    allowed = {
        "title",
        "project_type",
        "workflow_id",
        "stage",
        "brief",
        "bible",
        "settings",
        "custom_fields",
    }
    for key, value in patch.items():
        if key in allowed:
            data[key] = value
    updated = CreativeProject.model_validate(data)
    saved = uow.projects.update(
        updated,
        expected_revision=expected_revision,
    )

    # Keep system Brief/Bible artifacts aligned with editable project fields
    # so the Agent context has one current source of truth.
    artifact_kinds = []
    if "brief" in patch:
        artifact_kinds.append(
            (
                "brief",
                "创作 Brief",
                "video-studio/brief@1",
                saved.brief.model_dump(mode="json"),
            )
        )
    if "bible" in patch:
        artifact_kinds.append(
            (
                "project_bible",
                "项目 Bible",
                "video-studio/project-bible@1",
                saved.bible.model_dump(mode="json"),
            )
        )
    if artifact_kinds:
        artifacts = uow.artifacts.list(
            project_id,
            unit_id=None,
        )
        for kind, name, schema_id, payload in artifact_kinds:
            artifact = next(
                (
                    item
                    for item in artifacts
                    if item["kind"] == kind
                ),
                None,
            )
            if artifact is None:
                uow.artifacts.create(
                    project_id=project_id,
                    unit_id=None,
                    kind=kind,
                    name=name,
                    schema_id=schema_id,
                    payload=payload,
                    source="user",
                )
                continue
            current = artifact.get("current_version") or {}
            if current.get("payload") != payload:
                uow.artifacts.add_version(
                    artifact["id"],
                    payload,
                    source="user",
                    parent_version_id=current.get("id"),
                    note="项目设定已保存",
                )
    return saved


def create_units(
    uow,
    project_id: str,
    definitions: list[dict[str, Any]],
) -> list[CreativeUnit]:
    uow.projects.get(project_id)
    now = time.time()
    units = []
    for index, definition in enumerate(definitions):
        units.append(
            CreativeUnit(
                id=definition.get("id") or uuid.uuid4().hex,
                project_id=project_id,
                parent_id=definition.get("parent_id"),
                unit_type=definition.get("unit_type") or "unit",
                order_index=float(
                    definition.get("order_index", index)
                ),
                title=(
                    definition.get("title")
                    or "未命名单元"
                ).strip(),
                summary=definition.get("summary", ""),
                stage=definition.get("stage", "brief"),
                continuity_summary=definition.get(
                    "continuity_summary",
                    "",
                ),
                custom_fields=definition.get(
                    "custom_fields",
                    {},
                ),
                created_at=now,
                updated_at=now,
            )
        )
    return uow.units.create_many(units)
