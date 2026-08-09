from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    project_type: Mapped[str] = mapped_column(String(100), nullable=False, default="freeform")
    workflow_id: Mapped[str] = mapped_column(String(100), nullable=False, default="freeform")
    stage: Mapped[str] = mapped_column(String(100), nullable=False, default="brief")
    brief_json: Mapped[str] = mapped_column(Text, nullable=False)
    bible_json: Mapped[str] = mapped_column(Text, nullable=False)
    settings_json: Mapped[str] = mapped_column(Text, nullable=False)
    custom_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    units: Mapped[list["CreativeUnitRow"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class CreativeUnitRow(Base):
    __tablename__ = "creative_units"
    __table_args__ = (
        Index("ix_units_project_parent_order", "project_id", "parent_id", "order_index"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("creative_units.id", ondelete="CASCADE"), nullable=True, index=True
    )
    unit_type: Mapped[str] = mapped_column(String(100), nullable=False, default="unit")
    order_index: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stage: Mapped[str] = mapped_column(String(100), nullable=False, default="brief")
    continuity_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    custom_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    project: Mapped[ProjectRow] = relationship(back_populates="units")
    parent: Mapped["CreativeUnitRow | None"] = relationship(
        remote_side="CreativeUnitRow.id", back_populates="children"
    )
    children: Mapped[list["CreativeUnitRow"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan", single_parent=True
    )


class ConversationRow(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_id: Mapped[str | None] = mapped_column(
        ForeignKey("creative_units.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="新对话")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    messages: Mapped[list["MessageRow"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class MessageRow(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "seq", name="uq_message_seq"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    proposal_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    conversation: Mapped[ConversationRow] = relationship(back_populates="messages")


class ArtifactRow(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        Index("ix_artifacts_project_unit_kind", "project_id", "unit_id", "kind"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_id: Mapped[str | None] = mapped_column(
        ForeignKey("creative_units.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    schema_id: Mapped[str] = mapped_column(String(200), nullable=False, default="freeform")
    current_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    versions: Mapped[list["ArtifactVersionRow"]] = relationship(
        back_populates="artifact",
        cascade="all, delete-orphan",
        foreign_keys="ArtifactVersionRow.artifact_id",
    )


class ArtifactVersionRow(Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (UniqueConstraint("artifact_id", "version", name="uq_artifact_version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="user")
    parent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    artifact: Mapped[ArtifactRow] = relationship(
        back_populates="versions", foreign_keys=[artifact_id]
    )


class ProposalRow(Base):
    __tablename__ = "change_proposals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_id: Mapped[str | None] = mapped_column(
        ForeignKey("creative_units.id", ondelete="CASCADE"), nullable=True
    )
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=True
    )
    artifact_kind: Mapped[str] = mapped_column(String(100), nullable=False)
    base_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    operations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    proposed_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


class ProviderProfileRow(Base):
    __tablename__ = "provider_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    capability_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    adapter: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    api_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    settings_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    models: Mapped[list["ModelProfileRow"]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )


class ModelProfileRow(Base):
    __tablename__ = "model_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_profile_id: Mapped[str] = mapped_column(
        ForeignKey("provider_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    model_id: Mapped[str] = mapped_column(String(300), nullable=False)
    capability_type: Mapped[str] = mapped_column(String(50), nullable=False)
    capabilities_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    defaults_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    provider: Mapped[ProviderProfileRow] = relationship(back_populates="models")


class AssetRow(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_id: Mapped[str | None] = mapped_column(
        ForeignKey("creative_units.id", ondelete="CASCADE"), nullable=True, index=True
    )
    shot_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(200), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parent_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    generation_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_id: Mapped[str | None] = mapped_column(
        ForeignKey("creative_units.id", ondelete="CASCADE"), nullable=True, index=True
    )
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


class JobEventRow(Base):
    __tablename__ = "job_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    stage: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class NodeRunRow(Base):
    __tablename__ = "node_runs"
    __table_args__ = (Index("ix_node_input_hash", "node_key", "input_hash"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    output_refs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


class WorkflowRow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[str] = mapped_column(String(50), nullable=False, default="1")
    definition_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
