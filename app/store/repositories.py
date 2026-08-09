from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import func, select

from app.domain import (
    CreativeProject,
    CreativeUnit,
    ProjectBible,
    ProjectSettings,
)
from app.domain.brief import CreativeBrief
from app.domain.enums import ArtifactStatus, JobStatus, ProposalStatus

from .json_codec import dumps, loads
from .models import (
    ArtifactRow,
    ArtifactVersionRow,
    AssetRow,
    ConversationRow,
    CreativeUnitRow,
    JobEventRow,
    JobRow,
    MessageRow,
    ModelProfileRow,
    NodeRunRow,
    ProjectRow,
    ProposalRow,
    ProviderProfileRow,
    WorkflowRow,
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

    def list(self, project_id: str, unit_id: str | None = None) -> list[dict[str, Any]]:
        query = select(ArtifactRow).where(ArtifactRow.project_id == project_id)
        if unit_id is not None:
            query = query.where(ArtifactRow.unit_id == unit_id)
        rows = self.session.scalars(query.order_by(ArtifactRow.updated_at.desc())).all()
        return [self.get(row.id) for row in rows]

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
        artifact.updated_at = row.created_at
        return self._version(row)

    def versions(self, artifact_id: str) -> list[dict[str, Any]]:
        rows = self.session.scalars(
            select(ArtifactVersionRow)
            .where(ArtifactVersionRow.artifact_id == artifact_id)
            .order_by(ArtifactVersionRow.version.desc())
        ).all()
        return [self._version(row) for row in rows]

    def set_status(self, version_id: str, status: str) -> dict[str, Any]:
        row = self.session.get(ArtifactVersionRow, version_id)
        if row is None:
            raise NotFoundError(version_id)
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
        }

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

    def get(self, asset_id: str) -> dict[str, Any]:
        row = self.session.get(AssetRow, asset_id)
        if row is None:
            raise NotFoundError(asset_id)
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
        progress = row.progress
        if progress > 1:
            progress = progress / 100.0
        return {
            "id": row.id,
            "project_id": row.project_id,
            "unit_id": row.unit_id,
            "job_type": row.job_type,
            "status": row.status,
            "progress": progress,
            "cancel_requested": row.cancel_requested,
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
            row.progress = progress / 100.0 if progress > 1 else progress
        if result is not None:
            row.result_json = dumps(result)
        row.error = error
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

    def create_node_run(self, job_id: str, node_key: str, input_hash: str) -> dict[str, Any]:
        now = time.time()
        row = NodeRunRow(
            id=new_id(),
            job_id=job_id,
            node_key=node_key,
            status=JobStatus.QUEUED.value,
            input_hash=input_hash,
            output_refs_json="[]",
            error="",
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self.session.flush()
        return {
            "id": row.id,
            "job_id": row.job_id,
            "node_key": row.node_key,
            "status": row.status,
            "input_hash": row.input_hash,
            "output_refs": [],
        }


class WorkflowRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def _data(row: WorkflowRow) -> dict[str, Any]:
        definition = loads(row.definition_json, {})
        return {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "version": row.version,
            "definition": definition,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        definition = data.get("definition", {})
        row = WorkflowRow(
            id=data.get("id") or new_id(),
            name=data["name"],
            description=data.get("description", ""),
            version=str(definition.get("version") or data.get("version") or "1"),
            definition_json=dumps(definition),
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self.session.flush()
        return self._data(row)

    def list(self) -> list[dict[str, Any]]:
        rows = self.session.scalars(
            select(WorkflowRow).order_by(WorkflowRow.updated_at.desc())
        ).all()
        return [self._data(row) for row in rows]

    def get(self, workflow_id: str) -> dict[str, Any]:
        row = self.session.get(WorkflowRow, workflow_id)
        if row is None:
            raise NotFoundError(workflow_id)
        return self._data(row)

    def update(self, workflow_id: str, data: dict[str, Any]) -> dict[str, Any]:
        row = self.session.get(WorkflowRow, workflow_id)
        if row is None:
            raise NotFoundError(workflow_id)
        if "name" in data:
            row.name = data["name"]
        if "description" in data:
            row.description = data["description"]
        if "definition" in data:
            definition = data["definition"]
            row.definition_json = dumps(definition)
            row.version = str(definition.get("version") or row.version)
        row.updated_at = time.time()
        self.session.flush()
        return self._data(row)

    def delete(self, workflow_id: str) -> None:
        row = self.session.get(WorkflowRow, workflow_id)
        if row is None:
            raise NotFoundError(workflow_id)
        self.session.delete(row)
