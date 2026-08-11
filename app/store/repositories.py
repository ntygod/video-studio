from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import func, or_, select, text

from app.domain import (
    CreativeProject,
    CreativeUnit,
    ProjectBible,
    ProjectSettings,
)
from app.domain.brief import CreativeBrief
from app.domain.enums import ArtifactStatus, JobStatus, ProposalStatus

from .json_codec import dumps, loads
from .paging import decode_cursor, encode_cursor
from .models import (
    AgentStepRow,
    AgentTurnRow,
    ArtifactRow,
    ArtifactVersionRow,
    AssetRow,
    ConversationRow,
    CreativeUnitRow,
    JobEventRow,
    JobRow,
    MessageRow,
    ModelProfileRow,
    ProjectRow,
    ProposalRow,
    ProviderProfileRow,
)


def new_id() -> str:
    return uuid.uuid4().hex


class NotFoundError(KeyError):
    pass


class ConflictError(RuntimeError):
    pass


class ProjectRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def _domain(row: ProjectRow) -> CreativeProject:
        return CreativeProject(
            id=row.id,
            title=row.title,
            project_type=row.project_type,
            workflow_id=row.workflow_id,
            stage=row.stage,
            brief=CreativeBrief.model_validate(loads(row.brief_json, {})),
            bible=ProjectBible.model_validate(loads(row.bible_json, {})),
            settings=ProjectSettings.model_validate(loads(row.settings_json, {})),
            custom_fields=loads(row.custom_json, {}),
            revision=row.revision,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def create(self, project: CreativeProject) -> CreativeProject:
        row = ProjectRow(
            id=project.id,
            title=project.title,
            project_type=project.project_type,
            workflow_id=project.workflow_id,
            stage=project.stage,
            brief_json=dumps(project.brief.model_dump(mode="json")),
            bible_json=dumps(project.bible.model_dump(mode="json")),
            settings_json=dumps(project.settings.model_dump(mode="json")),
            custom_json=dumps(project.custom_fields),
            revision=project.revision,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )
        self.session.add(row)
        self.session.flush()
        return self._domain(row)

    def list(self) -> list[CreativeProject]:
        rows = self.session.scalars(
            select(ProjectRow).order_by(ProjectRow.updated_at.desc())
        ).all()
        return [self._domain(row) for row in rows]

    def get(self, project_id: str) -> CreativeProject:
        row = self.session.get(ProjectRow, project_id)
        if row is None:
            raise NotFoundError(project_id)
        return self._domain(row)

    def update(self, project: CreativeProject, expected_revision: int) -> CreativeProject:
        row = self.session.get(ProjectRow, project.id)
        if row is None:
            raise NotFoundError(project.id)
        if row.revision != expected_revision:
            raise ConflictError(
                f"project revision changed: expected {expected_revision}, actual {row.revision}"
            )
        row.title = project.title
        row.project_type = project.project_type
        row.workflow_id = project.workflow_id
        row.stage = project.stage
        row.brief_json = dumps(project.brief.model_dump(mode="json"))
        row.bible_json = dumps(project.bible.model_dump(mode="json"))
        row.settings_json = dumps(project.settings.model_dump(mode="json"))
        row.custom_json = dumps(project.custom_fields)
        row.revision += 1
        row.updated_at = time.time()
        self.session.flush()
        return self._domain(row)

    def delete(self, project_id: str) -> None:
        row = self.session.get(ProjectRow, project_id)
        if row is None:
            raise NotFoundError(project_id)
        self.session.delete(row)

    def stats(self, project_id: str) -> dict[str, Any]:
        """单项目统计：单元/稿件/素材/待处理提案数量与最近活动时间（T3.1）。"""
        row = self.session.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM creative_units WHERE project_id=:pid) AS unit_count,
                  (SELECT COUNT(*) FROM artifacts WHERE project_id=:pid) AS artifact_count,
                  (SELECT COUNT(*) FROM assets WHERE project_id=:pid) AS asset_count,
                  (SELECT COUNT(*) FROM change_proposals WHERE project_id=:pid AND status='pending') AS pending_proposal_count,
                  COALESCE((
                    SELECT MAX(u) FROM (
                      SELECT updated_at AS u FROM projects WHERE id=:pid
                      UNION ALL SELECT updated_at FROM creative_units WHERE project_id=:pid
                      UNION ALL SELECT updated_at FROM artifacts WHERE project_id=:pid
                      UNION ALL SELECT updated_at FROM assets WHERE project_id=:pid
                      UNION ALL SELECT updated_at FROM jobs WHERE project_id=:pid
                      UNION ALL SELECT updated_at FROM change_proposals WHERE project_id=:pid
                    )
                  ), p.updated_at) AS last_activity
                FROM projects p WHERE p.id=:pid
                """
            ),
            {"pid": project_id},
        ).mappings().one()
        return dict(row)

    def summaries(self) -> list[dict[str, Any]]:
        """项目列表聚合字段：封面素材、待处理提案数、最近活动、单元数（T3.4）。"""
        rows = self.session.execute(
            text(
                """
                SELECT p.id,
                  (SELECT a.id FROM assets a
                   WHERE a.project_id=p.id AND a.kind IN ('render','image')
                   ORDER BY a.created_at DESC, a.id DESC LIMIT 1) AS cover_asset_id,
                  COALESCE((
                    SELECT a.uri FROM assets a
                    WHERE a.project_id=p.id AND a.kind IN ('render','image')
                    ORDER BY a.created_at DESC, a.id DESC LIMIT 1
                  ), '') AS cover_asset_uri,
                  (SELECT COUNT(*) FROM change_proposals c
                   WHERE c.project_id=p.id AND c.status='pending') AS pending_proposal_count,
                  COALESCE((
                    SELECT MAX(u) FROM (
                      SELECT p.updated_at AS u
                      UNION ALL SELECT updated_at FROM creative_units WHERE project_id=p.id
                      UNION ALL SELECT updated_at FROM artifacts WHERE project_id=p.id
                      UNION ALL SELECT updated_at FROM assets WHERE project_id=p.id
                      UNION ALL SELECT updated_at FROM jobs WHERE project_id=p.id
                      UNION ALL SELECT updated_at FROM change_proposals WHERE project_id=p.id
                    )
                  ), p.updated_at) AS last_activity,
                  (SELECT COUNT(*) FROM creative_units WHERE project_id=p.id) AS unit_count
                FROM projects p
                ORDER BY p.updated_at DESC
                """
            )
        ).mappings().all()
        return [dict(row) for row in rows]


class UnitRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def _domain(row: CreativeUnitRow) -> CreativeUnit:
        return CreativeUnit(
            id=row.id,
            project_id=row.project_id,
            parent_id=row.parent_id,
            unit_type=row.unit_type,
            order_index=row.order_index,
            title=row.title,
            summary=row.summary,
            stage=row.stage,
            continuity_summary=row.continuity_summary,
            custom_fields=loads(row.custom_json, {}),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def create(self, unit: CreativeUnit) -> CreativeUnit:
        if self.session.get(ProjectRow, unit.project_id) is None:
            raise NotFoundError(unit.project_id)
        if unit.parent_id:
            parent = self.session.get(CreativeUnitRow, unit.parent_id)
            if parent is None or parent.project_id != unit.project_id:
                raise NotFoundError(unit.parent_id)
        row = CreativeUnitRow(
            id=unit.id,
            project_id=unit.project_id,
            parent_id=unit.parent_id,
            unit_type=unit.unit_type,
            order_index=unit.order_index,
            title=unit.title,
            summary=unit.summary,
            stage=unit.stage,
            continuity_summary=unit.continuity_summary,
            custom_json=dumps(unit.custom_fields),
            created_at=unit.created_at,
            updated_at=unit.updated_at,
        )
        self.session.add(row)
        self.session.flush()
        return self._domain(row)

    def create_many(self, units: list[CreativeUnit]) -> list[CreativeUnit]:
        created = []
        for unit in units:
            created.append(self.create(unit))
        return created

    def list(self, project_id: str, parent_id: str | None = None) -> list[CreativeUnit]:
        query = select(CreativeUnitRow).where(CreativeUnitRow.project_id == project_id)
        if parent_id is not None:
            query = query.where(CreativeUnitRow.parent_id == parent_id)
        rows = self.session.scalars(
            query.order_by(CreativeUnitRow.order_index, CreativeUnitRow.created_at)
        ).all()
        return [self._domain(row) for row in rows]

    def child_counts(self, project_id: str) -> dict[str | None, int]:
        """一次聚合出每个父级下的直属子单元数量。

        供 Agent 的 list_units 工具使用——逐个单元再查一次子级会在长篇项目里
        变成上百次查询。
        """
        rows = self.session.execute(
            select(CreativeUnitRow.parent_id, func.count(CreativeUnitRow.id))
            .where(CreativeUnitRow.project_id == project_id)
            .group_by(CreativeUnitRow.parent_id)
        ).all()
        return {parent_id: count for parent_id, count in rows}

    def list_page(
        self,
        project_id: str,
        parent_id: str | None = None,
        depth: int = 1,
        limit: int = 200,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """按层展开子树并分页；游标为 (created_at, id)，先父后子（T3.1）。"""
        depth = max(1, int(depth))
        limit = max(1, min(int(limit), 500))
        rows = self._rows_flat(project_id, parent_id=parent_id, depth=depth)
        key = decode_cursor(cursor)
        if key is not None:
            rows = [
                row
                for row in rows
                if (row.order_index, row.created_at, row.id) > tuple(key)
            ]
        page_items = rows[:limit]
        next_cursor = (
            encode_cursor(
                page_items[-1].order_index, page_items[-1].created_at, page_items[-1].id
            )
            if len(rows) > limit
            else None
        )
        return {
            "items": [self._domain(row) for row in page_items],
            "next_cursor": next_cursor,
        }

    def _rows_flat(
        self, project_id: str, parent_id: str | None, depth: int
    ) -> list[Any]:
        result: list[Any] = []
        seen: set[str] = set()
        current: list[str | None] = [parent_id]
        for _ in range(depth):
            if not current:
                break
            query = select(CreativeUnitRow).where(
                CreativeUnitRow.project_id == project_id
            )
            none_parents = [pid for pid in current if pid is None]
            real_parents = [pid for pid in current if pid is not None]
            if none_parents and real_parents:
                query = query.where(
                    or_(
                        CreativeUnitRow.parent_id.is_(None),
                        CreativeUnitRow.parent_id.in_(real_parents),
                    )
                )
            elif none_parents:
                query = query.where(CreativeUnitRow.parent_id.is_(None))
            else:
                query = query.where(CreativeUnitRow.parent_id.in_(real_parents))
            level = sorted(
                self.session.scalars(query).all(),
                key=lambda row: (row.order_index, row.created_at, row.id),
            )
            fresh = [row for row in level if row.id not in seen]
            for row in fresh:
                seen.add(row.id)
            result.extend(fresh)
            current = [row.id for row in fresh]
        return result

    def get(self, unit_id: str) -> CreativeUnit:
        row = self.session.get(CreativeUnitRow, unit_id)
        if row is None:
            raise NotFoundError(unit_id)
        return self._domain(row)

    def update(self, unit: CreativeUnit) -> CreativeUnit:
        row = self.session.get(CreativeUnitRow, unit.id)
        if row is None:
            raise NotFoundError(unit.id)
        row.parent_id = unit.parent_id
        row.unit_type = unit.unit_type
        row.order_index = unit.order_index
        row.title = unit.title
        row.summary = unit.summary
        row.stage = unit.stage
        row.continuity_summary = unit.continuity_summary
        row.custom_json = dumps(unit.custom_fields)
        row.updated_at = time.time()
        self.session.flush()
        return self._domain(row)

    def delete(self, unit_id: str) -> None:
        row = self.session.get(CreativeUnitRow, unit_id)
        if row is None:
            raise NotFoundError(unit_id)
        self.session.delete(row)


class ConversationRepository:
    def __init__(self, session):
        self.session = session

    def create(self, project_id: str, unit_id: str | None, title: str) -> dict[str, Any]:
        now = time.time()
        row = ConversationRow(
            id=new_id(),
            project_id=project_id,
            unit_id=unit_id,
            title=title or "新对话",
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self.session.flush()
        return self._conversation(row)

    @staticmethod
    def _conversation(row: ConversationRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "unit_id": row.unit_id,
            "title": row.title,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _message(row: MessageRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "conversation_id": row.conversation_id,
            "seq": row.seq,
            "role": row.role,
            "content": row.content,
            "proposal_ids": loads(row.proposal_ids_json, []),
            "created_at": row.created_at,
        }

    def get(self, conversation_id: str, include_messages: bool = True) -> dict[str, Any]:
        row = self.session.get(ConversationRow, conversation_id)
        if row is None:
            raise NotFoundError(conversation_id)
        data = self._conversation(row)
        if include_messages:
            data["messages"] = self.list_messages(conversation_id)
        return data

    def list(self, project_id: str, unit_id: str | None = None) -> list[dict[str, Any]]:
        query = select(ConversationRow).where(ConversationRow.project_id == project_id)
        if unit_id is not None:
            query = query.where(ConversationRow.unit_id == unit_id)
        rows = self.session.scalars(query.order_by(ConversationRow.updated_at.desc())).all()
        return [self._conversation(row) for row in rows]

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        proposal_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        conversation = self.session.get(ConversationRow, conversation_id)
        if conversation is None:
            raise NotFoundError(conversation_id)
        seq = self.session.scalar(
            select(func.coalesce(func.max(MessageRow.seq), 0)).where(
                MessageRow.conversation_id == conversation_id
            )
        ) + 1
        row = MessageRow(
            id=new_id(),
            conversation_id=conversation_id,
            seq=seq,
            role=role,
            content=content,
            proposal_ids_json=dumps(proposal_ids or []),
            created_at=time.time(),
        )
        conversation.updated_at = row.created_at
        self.session.add(row)
        self.session.flush()
        return self._message(row)

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = self.session.scalars(
            select(MessageRow)
            .where(MessageRow.conversation_id == conversation_id)
            .order_by(MessageRow.seq)
        ).all()
        return [self._message(row) for row in rows]

    def delete(self, conversation_id: str) -> None:
        row = self.session.get(ConversationRow, conversation_id)
        if row is None:
            raise NotFoundError(conversation_id)
        self.session.delete(row)

    def set_role(self, message_id: str, role: str) -> None:
        """滚动摘要压缩后把旧消息标记为 compacted，不再进入 LLM 上下文。"""
        row = self.session.get(MessageRow, message_id)
        if row is None:
            raise NotFoundError(message_id)
        row.role = role
        self.session.flush()


class ArtifactRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def _artifact(row: ArtifactRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "unit_id": row.unit_id,
            "kind": row.kind,
            "name": row.name,
            "schema_id": row.schema_id,
            "current_version_id": row.current_version_id,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _version(row: ArtifactVersionRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "artifact_id": row.artifact_id,
            "version": row.version,
            "status": row.status,
            "schema_version": row.schema_version,
            "payload": loads(row.payload_json, {}),
            "source": row.source,
            "parent_version_id": row.parent_version_id,
            "note": row.note,
            "created_at": row.created_at,
        }

    def create(
        self,
        project_id: str,
        unit_id: str | None,
        kind: str,
        name: str,
        schema_id: str,
        payload: dict[str, Any],
        source: str = "user",
    ) -> dict[str, Any]:
        now = time.time()
        artifact = ArtifactRow(
            id=new_id(),
            project_id=project_id,
            unit_id=unit_id,
            kind=kind,
            name=name,
            schema_id=schema_id,
            current_version_id=None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(artifact)
        self.session.flush()
        version = self.add_version(artifact.id, payload, source=source)
        return {**self._artifact(artifact), "current_version": version}

    def get(self, artifact_id: str) -> dict[str, Any]:
        row = self.session.get(ArtifactRow, artifact_id)
        if row is None:
            raise NotFoundError(artifact_id)
        data = self._artifact(row)
        if row.current_version_id:
            version = self.session.get(ArtifactVersionRow, row.current_version_id)
            data["current_version"] = self._version(version) if version else None
        return data

    def find_latest(
        self,
        project_id: str,
        unit_id: str | None,
        kind: str,
    ) -> dict[str, Any] | None:
        """按项目、精确作用域与类型查找最近更新的一份稿件。

        ``unit_id=None`` 表示项目级稿件，不能退化成“不筛选单元”，否则项目级
        时间线可能错误复用某个具体单元的时间线。
        """
        query = (
            select(ArtifactRow)
            .where(ArtifactRow.project_id == project_id)
            .where(ArtifactRow.kind == kind)
        )
        if unit_id is None:
            query = query.where(ArtifactRow.unit_id.is_(None))
        else:
            query = query.where(ArtifactRow.unit_id == unit_id)
        row = self.session.scalar(
            query.order_by(ArtifactRow.updated_at.desc(), ArtifactRow.created_at.desc())
        )
        return self.get(row.id) if row else None

    def delete(self, artifact_id: str) -> None:
        row = self.session.get(ArtifactRow, artifact_id)
        if row is None:
            raise NotFoundError(artifact_id)
        self.session.delete(row)

    def list(
        self,
        project_id: str,
        unit_id: str | None = None,
        include_payload: bool = True,
    ) -> list[dict[str, Any]]:
        """一次 outerjoin 取出稿件与当前版本，避免每条再查一次版本（修 S2）。

        include_payload=False 时不解析 payload_json，列表场景不回正文。
        """
        query = (
            select(ArtifactRow, ArtifactVersionRow)
            .outerjoin(
                ArtifactVersionRow,
                ArtifactRow.current_version_id == ArtifactVersionRow.id,
            )
            .where(ArtifactRow.project_id == project_id)
        )
        if unit_id is not None:
            query = query.where(ArtifactRow.unit_id == unit_id)
        rows = self.session.execute(
            query.order_by(ArtifactRow.updated_at.desc())
        ).all()
        result = []
        for artifact_row, version_row in rows:
            data = self._artifact(artifact_row)
            if version_row is None:
                data["current_version"] = None
                result.append(data)
                continue
            version = self._version(version_row)
            if not include_payload:
                version.pop("payload", None)
            data["current_version"] = version
            result.append(data)
        return result

    def unit_ids_with_artifacts(self, project_id: str) -> set[str]:
        """一次查询取出「有稿件」的单元 id 集合，替代逐单元判断。"""
        rows = self.session.execute(
            select(ArtifactRow.unit_id)
            .where(ArtifactRow.project_id == project_id)
            .where(ArtifactRow.unit_id.is_not(None))
            .distinct()
        ).all()
        return {row[0] for row in rows}

    def list_page(
        self,
        project_id: str,
        unit_id: str | None = None,
        kind: str | None = None,
        include_payload: bool = False,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """稿件分页（T3.1）：一次 outerjoin + (created_at,id) 游标，默认不带正文。"""
        limit = max(1, min(int(limit), 200))
        query = (
            select(ArtifactRow, ArtifactVersionRow)
            .outerjoin(
                ArtifactVersionRow,
                ArtifactRow.current_version_id == ArtifactVersionRow.id,
            )
            .where(ArtifactRow.project_id == project_id)
        )
        if unit_id is not None:
            query = query.where(ArtifactRow.unit_id == unit_id)
        if kind:
            query = query.where(ArtifactRow.kind == kind)
        pairs = self.session.execute(
            query.order_by(ArtifactRow.created_at.desc(), ArtifactRow.id.desc())
        ).all()
        key = decode_cursor(cursor)
        if key is not None:
            pairs = [
                pair
                for pair in pairs
                if (pair[0].created_at, pair[0].id) < tuple(key)
            ]
        items = []
        for artifact_row, version_row in pairs[:limit]:
            data = self._artifact(artifact_row)
            if version_row is None:
                data["current_version"] = None
            else:
                version = self._version(version_row)
                if not include_payload:
                    version.pop("payload", None)
                data["current_version"] = version
            items.append(data)
        next_cursor = (
            encode_cursor(pairs[limit - 1][0].created_at, pairs[limit - 1][0].id)
            if len(pairs) > limit
            else None
        )
        return {"items": items, "next_cursor": next_cursor}

    def add_version(
        self,
        artifact_id: str,
        payload: dict[str, Any],
        source: str = "user",
        status: str = ArtifactStatus.DRAFT.value,
        parent_version_id: str | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        artifact = self.session.get(ArtifactRow, artifact_id)
        if artifact is None:
            raise NotFoundError(artifact_id)
        if artifact.current_version_id:
            current = self.session.get(ArtifactVersionRow, artifact.current_version_id)
            if current and current.status == ArtifactStatus.LOCKED.value:
                raise ConflictError("artifact is locked")
        version_number = self.session.scalar(
            select(func.coalesce(func.max(ArtifactVersionRow.version), 0)).where(
                ArtifactVersionRow.artifact_id == artifact_id
            )
        ) + 1
        row = ArtifactVersionRow(
            id=new_id(),
            artifact_id=artifact_id,
            version=version_number,
            status=status,
            schema_version=1,
            payload_json=dumps(payload),
            source=source,
            parent_version_id=parent_version_id or artifact.current_version_id,
            note=note,
            created_at=time.time(),
        )
        self.session.add(row)
        self.session.flush()
        artifact.current_version_id = row.id
        artifact.revision += 1
        artifact.updated_at = row.created_at
        return self._version(row)

    def versions(self, artifact_id: str) -> list[dict[str, Any]]:
        rows = self.session.scalars(
            select(ArtifactVersionRow)
            .where(ArtifactVersionRow.artifact_id == artifact_id)
            .order_by(ArtifactVersionRow.version.desc())
        ).all()
        return [self._version(row) for row in rows]

    def get_version(self, version_id: str) -> dict[str, Any]:
        row = self.session.get(ArtifactVersionRow, version_id)
        if row is None:
            raise NotFoundError(version_id)
        return self._version(row)

    # 版本状态机（T4.4）：只能前进，locked 为终态。
    _STATUS_TRANSITIONS: dict[str, set[str]] = {
        "draft": {"proposed", "approved", "locked"},
        "proposed": {"approved", "locked"},
        "approved": {"locked"},
        "locked": set(),
    }

    def set_status(self, version_id: str, status: str) -> dict[str, Any]:
        row = self.session.get(ArtifactVersionRow, version_id)
        if row is None:
            raise NotFoundError(version_id)
        if status != row.status and status not in self._STATUS_TRANSITIONS.get(row.status, set()):
            raise ConflictError(
                f"cannot move version status {row.status} -> {status}"
            )
        row.status = status
        self.session.flush()
        return self._version(row)


class ProposalRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def _data(row: ProposalRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "unit_id": row.unit_id,
            "artifact_id": row.artifact_id,
            "artifact_kind": row.artifact_kind,
            "base_version_id": row.base_version_id,
            "title": row.title,
            "rationale": row.rationale,
            "operations": loads(row.operations_json, []),
            "proposed_payload": loads(row.proposed_payload_json, None),
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        row = ProposalRow(
            id=data.get("id") or new_id(),
            project_id=data["project_id"],
            unit_id=data.get("unit_id"),
            artifact_id=data.get("artifact_id"),
            artifact_kind=data["artifact_kind"],
            base_version_id=data.get("base_version_id"),
            title=data["title"],
            rationale=data.get("rationale", ""),
            operations_json=dumps(data.get("operations", [])),
            proposed_payload_json=(
                dumps(data["proposed_payload"])
                if data.get("proposed_payload") is not None
                else None
            ),
            status=ProposalStatus.PENDING.value,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self.session.flush()
        return self._data(row)

    def get(self, proposal_id: str) -> dict[str, Any]:
        row = self.session.get(ProposalRow, proposal_id)
        if row is None:
            raise NotFoundError(proposal_id)
        return self._data(row)

    def list(self, project_id: str, status: str | None = None) -> list[dict[str, Any]]:
        query = select(ProposalRow).where(ProposalRow.project_id == project_id)
        if status:
            query = query.where(ProposalRow.status == status)
        rows = self.session.scalars(query.order_by(ProposalRow.created_at.desc())).all()
        return [self._data(row) for row in rows]

    def list_page(
        self,
        project_id: str,
        status: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """提案分页（T3.1）。"""
        limit = max(1, min(int(limit), 200))
        query = select(ProposalRow).where(ProposalRow.project_id == project_id)
        if status:
            query = query.where(ProposalRow.status == status)
        rows = self.session.scalars(
            query.order_by(ProposalRow.created_at.desc(), ProposalRow.id.desc())
        ).all()
        key = decode_cursor(cursor)
        if key is not None:
            rows = [row for row in rows if (row.created_at, row.id) < tuple(key)]
        next_cursor = (
            encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id)
            if len(rows) > limit
            else None
        )
        return {
            "items": [self._data(row) for row in rows[:limit]],
            "next_cursor": next_cursor,
        }

    def set_status(self, proposal_id: str, status: str) -> dict[str, Any]:
        row = self.session.get(ProposalRow, proposal_id)
        if row is None:
            raise NotFoundError(proposal_id)
        if row.status != ProposalStatus.PENDING.value:
            raise ConflictError(f"proposal already {row.status}")
        row.status = status
        row.updated_at = time.time()
        self.session.flush()
        return self._data(row)


class ProviderRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def _mask(secret: str) -> str:
        if not secret:
            return ""
        if len(secret) < 10:
            return "***"
        return secret[:4] + "***" + secret[-3:]

    def _data(self, row: ProviderProfileRow, include_secret: bool = False) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "capability_type": row.capability_type,
            "adapter": row.adapter,
            "base_url": row.base_url,
            "api_key": row.api_key if include_secret else self._mask(row.api_key),
            "enabled": row.enabled,
            "settings": loads(row.settings_json, {}),
            "models": [
                {
                    "id": model.id,
                    "name": model.name,
                    "model_id": model.model_id,
                    "capability_type": model.capability_type,
                    "capabilities": loads(model.capabilities_json, {}),
                    "defaults": loads(model.defaults_json, {}),
                    "is_default": model.is_default,
                }
                for model in row.models
            ],
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        row = ProviderProfileRow(
            id=data.get("id") or new_id(),
            name=data["name"],
            capability_type=data["capability_type"],
            adapter=data["adapter"],
            base_url=data.get("base_url", ""),
            api_key=data.get("api_key", ""),
            enabled=data.get("enabled", True),
            settings_json=dumps(data.get("settings", {})),
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self.session.flush()
        for model in data.get("models", []):
            self.add_model(row.id, model)
        self._apply_default_models(data)
        self.session.refresh(row)
        return self._data(row)

    def add_model(self, provider_id: str, data: dict[str, Any]) -> dict[str, Any]:
        row = ModelProfileRow(
            id=data.get("id") or new_id(),
            provider_profile_id=provider_id,
            name=data.get("name") or data["model_id"],
            model_id=data["model_id"],
            capability_type=data.get("capability_type", ""),
            capabilities_json=dumps(data.get("capabilities", {})),
            defaults_json=dumps(data.get("defaults", {})),
            is_default=data.get("is_default", False),
        )
        self.session.add(row)
        self.session.flush()
        return {
            "id": row.id,
            "name": row.name,
            "model_id": row.model_id,
            "capability_type": row.capability_type,
            "capabilities": loads(row.capabilities_json, {}),
            "defaults": loads(row.defaults_json, {}),
            "is_default": row.is_default,
        }

    def _apply_default_models(self, provider_data: dict[str, Any]) -> None:
        """同一能力全局只保留一个默认模型；本次提交中第一个标记默认的生效。"""
        provider_capability = provider_data.get("capability_type") or ""
        picked: dict[str, str] = {}
        for model in provider_data.get("models") or []:
            capability = model.get("capability_type") or provider_capability
            if capability and model.get("is_default"):
                picked.setdefault(capability, model["model_id"])
        if not picked:
            return
        rows = self.session.scalars(
            select(ModelProfileRow).where(
                ModelProfileRow.capability_type.in_(list(picked))
            )
        ).all()
        for row in rows:
            row.is_default = picked.get(row.capability_type) == row.model_id

    def list(self) -> list[dict[str, Any]]:
        rows = self.session.scalars(
            select(ProviderProfileRow).order_by(ProviderProfileRow.capability_type, ProviderProfileRow.name)
        ).all()
        return [self._data(row) for row in rows]

    def get(self, provider_id: str, include_secret: bool = False) -> dict[str, Any]:
        row = self.session.get(ProviderProfileRow, provider_id)
        if row is None:
            raise NotFoundError(provider_id)
        return self._data(row, include_secret=include_secret)

    def update(self, provider_id: str, data: dict[str, Any]) -> dict[str, Any]:
        row = self.session.get(ProviderProfileRow, provider_id)
        if row is None:
            raise NotFoundError(provider_id)
        for field in ("name", "capability_type", "adapter", "base_url", "enabled"):
            if field in data:
                setattr(row, field, data[field])
        if data.get("api_key") and "***" not in data["api_key"]:
            row.api_key = data["api_key"]
        if "settings" in data:
            row.settings_json = dumps(data["settings"])
        if data.get("models") is not None:
            for model in list(row.models):
                self.session.delete(model)
            row.models.clear()
            self.session.flush()
            for model in data["models"]:
                self.add_model(row.id, model)
            self._apply_default_models(data)
            # row.models was loaded before replacement and still points at the
            # cleared in-memory collection. Expire it so the response (and any
            # work in the same transaction) sees the newly inserted rows.
            self.session.expire(row, ["models"])
        row.updated_at = time.time()
        self.session.flush()
        return self._data(row)

    def delete(self, provider_id: str) -> None:
        row = self.session.get(ProviderProfileRow, provider_id)
        if row is None:
            raise NotFoundError(provider_id)
        self.session.delete(row)


class AssetRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def _data(row: AssetRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "unit_id": row.unit_id,
            "shot_id": row.shot_id,
            "kind": row.kind,
            "name": row.name,
            "uri": row.uri,
            "thumb_uri": row.thumb_uri,
            "mime_type": row.mime_type,
            "sha256": row.sha256,
            "parent_asset_id": row.parent_asset_id,
            "generation": loads(row.generation_json, {}),
            "metadata": loads(row.metadata_json, {}),
            "created_at": row.created_at,
        }

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        row = AssetRow(
            id=data.get("id") or new_id(),
            project_id=data["project_id"],
            unit_id=data.get("unit_id"),
            shot_id=data.get("shot_id"),
            kind=data["kind"],
            name=data.get("name", ""),
            uri=data["uri"],
            thumb_uri=data.get("thumb_uri", ""),
            mime_type=data.get("mime_type", "application/octet-stream"),
            sha256=data.get("sha256", ""),
            parent_asset_id=data.get("parent_asset_id"),
            generation_json=dumps(data.get("generation", {})),
            metadata_json=dumps(data.get("metadata", {})),
            created_at=time.time(),
        )
        self.session.add(row)
        self.session.flush()
        return self._data(row)

    def list(self, project_id: str, unit_id: str | None = None) -> list[dict[str, Any]]:
        query = select(AssetRow).where(AssetRow.project_id == project_id)
        if unit_id is not None:
            query = query.where(AssetRow.unit_id == unit_id)
        rows = self.session.scalars(query.order_by(AssetRow.created_at.desc())).all()
        return [self._data(row) for row in rows]

    def list_page(
        self,
        project_id: str,
        unit_id: str | None = None,
        kind: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """素材分页（T3.1）。"""
        limit = max(1, min(int(limit), 200))
        query = select(AssetRow).where(AssetRow.project_id == project_id)
        if unit_id is not None:
            query = query.where(AssetRow.unit_id == unit_id)
        if kind:
            query = query.where(AssetRow.kind == kind)
        rows = self.session.scalars(
            query.order_by(AssetRow.created_at.desc(), AssetRow.id.desc())
        ).all()
        key = decode_cursor(cursor)
        if key is not None:
            rows = [row for row in rows if (row.created_at, row.id) < tuple(key)]
        next_cursor = (
            encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id)
            if len(rows) > limit
            else None
        )
        return {
            "items": [self._data(row) for row in rows[:limit]],
            "next_cursor": next_cursor,
        }

    def get(self, asset_id: str) -> dict[str, Any]:
        row = self.session.get(AssetRow, asset_id)
        if row is None:
            raise NotFoundError(asset_id)
        return self._data(row)

    def update_scope(
        self,
        asset_id: str,
        unit_id: str | None = None,
        shot_id: str | None = None,
    ) -> dict[str, Any]:
        row = self.session.get(AssetRow, asset_id)
        if row is None:
            raise NotFoundError(asset_id)
        if unit_id is not None:
            row.unit_id = unit_id or None
        if shot_id is not None:
            row.shot_id = shot_id or None
        self.session.flush()
        return self._data(row)

    def delete(self, asset_id: str) -> None:
        row = self.session.get(AssetRow, asset_id)
        if row is None:
            raise NotFoundError(asset_id)
        self.session.delete(row)


class JobRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def _data(row: JobRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "unit_id": row.unit_id,
            "job_type": row.job_type,
            "status": row.status,
            "progress": row.progress,
            "cancel_requested": row.cancel_requested,
            "attempt": row.attempt,
            "max_attempts": row.max_attempts,
            "parent_job_id": row.parent_job_id,
            "lease_until": row.lease_until,
            "worker_id": row.worker_id,
            "turn_id": row.turn_id,
            "payload": loads(row.payload_json, {}),
            "result": loads(row.result_json, None),
            "error": row.error,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        row = JobRow(
            id=data.get("id") or new_id(),
            project_id=data["project_id"],
            unit_id=data.get("unit_id"),
            job_type=data["job_type"],
            status=JobStatus.QUEUED.value,
            progress=0.0,
            cancel_requested=False,
            attempt=0,
            max_attempts=int(data.get("max_attempts") or 3),
            parent_job_id=data.get("parent_job_id"),
            lease_until=None,
            worker_id="",
            turn_id=data.get("turn_id"),
            payload_json=dumps(data.get("payload", {})),
            result_json=None,
            error="",
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self.session.flush()
        return self._data(row)

    def get(self, job_id: str) -> dict[str, Any]:
        row = self.session.get(JobRow, job_id)
        if row is None:
            raise NotFoundError(job_id)
        data = self._data(row)
        data["events"] = self.events(job_id)
        return data

    def list(self, project_id: str | None = None) -> list[dict[str, Any]]:
        query = select(JobRow)
        if project_id:
            query = query.where(JobRow.project_id == project_id)
        rows = self.session.scalars(query.order_by(JobRow.created_at.desc())).all()
        return [self._data(row) for row in rows]

    def list_page(
        self,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """任务分页（T3.1）。"""
        limit = max(1, min(int(limit), 200))
        query = select(JobRow)
        if project_id:
            query = query.where(JobRow.project_id == project_id)
        if status:
            query = query.where(JobRow.status == status)
        rows = self.session.scalars(
            query.order_by(JobRow.created_at.desc(), JobRow.id.desc())
        ).all()
        key = decode_cursor(cursor)
        if key is not None:
            rows = [row for row in rows if (row.created_at, row.id) < tuple(key)]
        next_cursor = (
            encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id)
            if len(rows) > limit
            else None
        )
        return {
            "items": [self._data(row) for row in rows[:limit]],
            "next_cursor": next_cursor,
        }

    def update_state(
        self,
        job_id: str,
        status: str,
        progress: float | None = None,
        result: dict[str, Any] | None = None,
        error: str = "",
    ) -> dict[str, Any]:
        row = self.session.get(JobRow, job_id)
        if row is None:
            raise NotFoundError(job_id)
        row.status = status
        if progress is not None:
            row.progress = progress
        if result is not None:
            row.result_json = dumps(result)
        row.error = error
        row.updated_at = time.time()
        self.session.flush()
        return self._data(row)

    def update_payload(self, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        row = self.session.get(JobRow, job_id)
        if row is None:
            raise NotFoundError(job_id)
        row.payload_json = dumps(payload)
        row.updated_at = time.time()
        self.session.flush()
        return self._data(row)

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        row = self.session.get(JobRow, job_id)
        if row is None:
            raise NotFoundError(job_id)
        row.cancel_requested = True
        row.updated_at = time.time()
        self.session.flush()
        return self._data(row)

    def add_event(
        self,
        job_id: str,
        message: str,
        level: str = "info",
        stage: str = "",
        progress: float | None = None,
    ) -> dict[str, Any]:
        row = JobEventRow(
            id=new_id(),
            job_id=job_id,
            level=level,
            stage=stage,
            message=message,
            progress=progress,
            created_at=time.time(),
        )
        self.session.add(row)
        self.session.flush()
        return {
            "id": row.id,
            "job_id": row.job_id,
            "level": row.level,
            "stage": row.stage,
            "message": row.message,
            "progress": row.progress,
            "created_at": row.created_at,
        }

    def events(self, job_id: str) -> list[dict[str, Any]]:
        rows = self.session.scalars(
            select(JobEventRow)
            .where(JobEventRow.job_id == job_id)
            .order_by(JobEventRow.created_at)
        ).all()
        return [
            {
                "id": row.id,
                "job_id": row.job_id,
                "level": row.level,
                "stage": row.stage,
                "message": row.message,
                "progress": row.progress,
                "created_at": row.created_at,
            }
            for row in rows
        ]


class AgentTurnRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def _step(row: AgentStepRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "turn_id": row.turn_id,
            "seq": row.seq,
            "kind": row.kind,
            "tool_name": row.tool_name,
            "arguments": loads(row.arguments_json, {}),
            "result": loads(row.result_json, {}),
            "summary": row.summary,
            "status": row.status,
            "error": row.error,
            "duration_ms": row.duration_ms,
            "created_at": row.created_at,
        }

    @staticmethod
    def _turn(row: AgentTurnRow, steps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        data = {
            "id": row.id,
            "conversation_id": row.conversation_id,
            "project_id": row.project_id,
            "unit_id": row.unit_id,
            "user_message_id": row.user_message_id,
            "assistant_message_id": row.assistant_message_id,
            "status": row.status,
            "context_refs": loads(row.context_refs_json, []),
            "created_entities": loads(row.created_entities_json, []),
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
            "error": row.error,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        if steps is not None:
            data["steps"] = steps
        return data

    def create(
        self,
        conversation_id: str,
        project_id: str,
        unit_id: str | None = None,
        context_refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        row = AgentTurnRow(
            id=new_id(),
            conversation_id=conversation_id,
            project_id=project_id,
            unit_id=unit_id,
            user_message_id=None,
            assistant_message_id=None,
            status="running",
            context_refs_json=dumps(context_refs or []),
            created_entities_json="[]",
            prompt_tokens=0,
            completion_tokens=0,
            error="",
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self.session.flush()
        return self._turn(row)

    def get(self, turn_id: str) -> dict[str, Any]:
        row = self.session.get(AgentTurnRow, turn_id)
        if row is None:
            raise NotFoundError(turn_id)
        return self._turn(row, steps=self.steps(turn_id))

    def list(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = self.session.scalars(
            select(AgentTurnRow)
            .where(AgentTurnRow.conversation_id == conversation_id)
            .order_by(AgentTurnRow.created_at.desc())
        ).all()
        return [self._turn(row) for row in rows]

    def steps(self, turn_id: str) -> list[dict[str, Any]]:
        rows = self.session.scalars(
            select(AgentStepRow)
            .where(AgentStepRow.turn_id == turn_id)
            .order_by(AgentStepRow.seq)
        ).all()
        return [self._step(row) for row in rows]

    def add_step(
        self,
        turn_id: str,
        kind: str,
        tool_name: str = "",
        arguments: dict[str, Any] | None = None,
        request_id: str = "",
    ) -> dict[str, Any]:
        turn = self.session.get(AgentTurnRow, turn_id)
        if turn is None:
            raise NotFoundError(turn_id)
        arguments = dict(arguments or {})
        if request_id:
            arguments["_request_id"] = request_id
        seq = self.session.scalar(
            select(func.coalesce(func.max(AgentStepRow.seq), 0)).where(
                AgentStepRow.turn_id == turn_id
            )
        ) + 1
        row = AgentStepRow(
            id=new_id(),
            turn_id=turn_id,
            seq=seq,
            kind=kind,
            tool_name=tool_name,
            arguments_json=dumps(arguments or {}),
            result_json="{}",
            summary="",
            status="running",
            error="",
            duration_ms=0,
            created_at=time.time(),
        )
        self.session.add(row)
        self.session.flush()
        return self._step(row)

    def finish_step(
        self,
        step_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        summary: str = "",
        error: str = "",
    ) -> dict[str, Any]:
        row = self.session.get(AgentStepRow, step_id)
        if row is None:
            raise NotFoundError(step_id)
        row.status = status
        if result is not None:
            row.result_json = dumps(result)
        row.summary = summary
        row.error = error
        row.duration_ms = int((time.time() - row.created_at) * 1000)
        self.session.flush()
        return self._step(row)

    def record_entity(self, turn_id: str, entity_type: str, entity_id: str) -> None:
        row = self.session.get(AgentTurnRow, turn_id)
        if row is None:
            raise NotFoundError(turn_id)
        entities = loads(row.created_entities_json, [])
        if not any(
            entity.get("type") == entity_type and entity.get("id") == entity_id
            for entity in entities
        ):
            entities.append({"type": entity_type, "id": entity_id})
            row.created_entities_json = dumps(entities)
            row.updated_at = time.time()
            self.session.flush()

    def set_messages(
        self,
        turn_id: str,
        user_message_id: str | None = None,
        assistant_message_id: str | None = None,
    ) -> dict[str, Any]:
        row = self.session.get(AgentTurnRow, turn_id)
        if row is None:
            raise NotFoundError(turn_id)
        if user_message_id is not None:
            row.user_message_id = user_message_id
        if assistant_message_id is not None:
            row.assistant_message_id = assistant_message_id
        row.updated_at = time.time()
        self.session.flush()
        return self._turn(row)

    def set_usage(self, turn_id: str, prompt_tokens: int, completion_tokens: int) -> dict[str, Any]:
        row = self.session.get(AgentTurnRow, turn_id)
        if row is None:
            raise NotFoundError(turn_id)
        row.prompt_tokens = prompt_tokens
        row.completion_tokens = completion_tokens
        row.updated_at = time.time()
        self.session.flush()
        return self._turn(row)

    def set_status(self, turn_id: str, status: str, error: str = "") -> dict[str, Any]:
        row = self.session.get(AgentTurnRow, turn_id)
        if row is None:
            raise NotFoundError(turn_id)
        row.status = status
        if error:
            row.error = error
        row.updated_at = time.time()
        self.session.flush()
        return self._turn(row)

    def revert(self, turn_id: str) -> dict[str, Any]:
        row = self.session.get(AgentTurnRow, turn_id)
        if row is None:
            raise NotFoundError(turn_id)
        entities = loads(row.created_entities_json, [])
        reverted: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for entry in reversed(entities):
            entity_type = entry.get("type")
            entity_id = entry.get("id")
            try:
                if entity_type == "artifact":
                    artifact = self.session.get(ArtifactRow, entity_id)
                    if artifact is None:
                        continue
                    if artifact.revision > 1:
                        skipped.append(entry)
                        continue
                    self.session.delete(artifact)
                elif entity_type == "unit":
                    unit = self.session.get(CreativeUnitRow, entity_id)
                    if unit is None:
                        continue
                    # 创建后从未被改过：updated_at == created_at；被用户移动/改名会推进 updated_at
                    if unit.updated_at > unit.created_at + 0.001:
                        skipped.append(entry)
                        continue
                    self.session.delete(unit)
                elif entity_type == "asset":
                    asset = self.session.get(AssetRow, entity_id)
                    if asset is None:
                        continue
                    self.session.delete(asset)
                elif entity_type == "job":
                    job = self.session.get(JobRow, entity_id)
                    if job is None:
                        continue
                    if job.status in ("queued", "running"):
                        job.cancel_requested = True
                        job.updated_at = time.time()
                    skipped.append(entry)
                    continue
                else:
                    skipped.append(entry)
                    continue
                reverted.append(entry)
            except Exception:
                skipped.append(entry)
        row.status = "reverted"
        row.updated_at = time.time()
        self.session.flush()
        return {"turn": self._turn(row), "reverted": reverted, "skipped": skipped}


class SearchRepository:
    """FTS5（trigram）检索单元与稿件；短查询自动回落 LIKE（T3.2）。"""

    def __init__(self, session):
        self.session = session

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @staticmethod
    def _snippet(text_value: str, query: str, radius: int = 60) -> str:
        text_value = (text_value or "").replace("\n", " ").replace("\r", " ")
        low = text_value.lower()
        index = low.find(query.lower())
        if index < 0:
            return text_value[: radius * 2]
        start = max(0, index - radius)
        end = min(len(text_value), index + len(query) + radius)
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(text_value) else ""
        return prefix + text_value[start:end].strip() + suffix

    def search(
        self, project_id: str, query: str, kind: str = "all", limit: int = 20
    ) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        limit = max(1, min(int(limit), 50))
        results: list[dict[str, Any]] = []
        if kind in ("all", "unit"):
            results.extend(self._search_units(project_id, query, limit))
        if kind in ("all", "artifact"):
            results.extend(self._search_artifacts(project_id, query, limit))
        return results[:limit]

    def _search_units(
        self, project_id: str, query: str, limit: int
    ) -> list[dict[str, Any]]:
        if len(query) >= 3:
            phrase = '"' + query.replace('"', " ") + '"'
            rows = self.session.execute(
                text(
                    "SELECT unit_id AS id, title, summary, continuity_summary "
                    "FROM units_fts WHERE project_id=:pid AND units_fts MATCH :q "
                    "ORDER BY rank LIMIT :lim"
                ),
                {"pid": project_id, "q": phrase, "lim": limit},
            ).mappings().all()
        else:
            pattern = "%" + self._escape_like(query) + "%"
            rows = self.session.execute(
                text(
                    "SELECT id, title, summary, continuity_summary FROM creative_units "
                    "WHERE project_id=:pid AND (title LIKE :q ESCAPE '\\' "
                    "OR summary LIKE :q ESCAPE '\\' OR continuity_summary LIKE :q ESCAPE '\\') "
                    "ORDER BY updated_at DESC LIMIT :lim"
                ),
                {"pid": project_id, "q": pattern, "lim": limit},
            ).mappings().all()
        result = []
        for row in rows:
            hay = " ".join(
                filter(
                    None,
                    (row["title"], row["summary"], row["continuity_summary"]),
                )
            )
            result.append(
                {
                    "type": "unit",
                    "id": row["id"],
                    "title": row["title"],
                    "snippet": self._snippet(hay, query),
                    "unit_id": row["id"],
                }
            )
        return result

    def _search_artifacts(
        self, project_id: str, query: str, limit: int
    ) -> list[dict[str, Any]]:
        if len(query) >= 3:
            phrase = '"' + query.replace('"', " ") + '"'
            rows = self.session.execute(
                text(
                    "SELECT artifact_id AS id, unit_id, name, body FROM artifacts_fts "
                    "WHERE project_id=:pid AND artifacts_fts MATCH :q "
                    "ORDER BY rank LIMIT :lim"
                ),
                {"pid": project_id, "q": phrase, "lim": limit},
            ).mappings().all()
        else:
            pattern = "%" + self._escape_like(query) + "%"
            rows = self.session.execute(
                text(
                    "SELECT a.id, a.unit_id, a.name, v.payload_json AS body "
                    "FROM artifacts a LEFT JOIN artifact_versions v ON v.id=a.current_version_id "
                    "WHERE a.project_id=:pid AND (a.name LIKE :q ESCAPE '\\' "
                    "OR v.payload_json LIKE :q ESCAPE '\\') "
                    "ORDER BY a.updated_at DESC LIMIT :lim"
                ),
                {"pid": project_id, "q": pattern, "lim": limit},
            ).mappings().all()
        result = []
        for row in rows:
            hay = " ".join(filter(None, (row["name"], row["body"] or "")))
            result.append(
                {
                    "type": "artifact",
                    "id": row["id"],
                    "title": row["name"],
                    "snippet": self._snippet(hay, query),
                    "unit_id": row["unit_id"],
                }
            )
        return result
