"""Version-level Artifact dependency, provenance and freshness models."""

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ArtifactDependencyRow(Base):
    __tablename__ = "artifact_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "upstream_version_id",
            "downstream_version_id",
            "dependency_type",
            name="uq_artifact_dependency_edge",
        ),
        Index(
            "ix_artifact_dependency_project_downstream",
            "project_id",
            "downstream_artifact_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    upstream_version_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    downstream_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    downstream_version_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dependency_type: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="derived_from",
    )
    metadata_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class AssetDependencyRow(Base):
    """Immutable Asset input used by one ArtifactVersion.

    ``upstream_asset_id`` intentionally has no foreign key. Asset deletion is
    a supported operation and the dependency must survive as a tombstone so
    the current downstream Artifact can explain which exact input is missing.
    The project and downstream references still cascade normally.
    """

    __tablename__ = "asset_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "upstream_asset_id",
            "downstream_version_id",
            "dependency_type",
            name="uq_asset_dependency_edge",
        ),
        Index(
            "ix_asset_dependency_project_downstream",
            "project_id",
            "downstream_artifact_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    upstream_asset_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    upstream_asset_snapshot_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    downstream_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    downstream_version_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dependency_type: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="uses_asset",
    )
    metadata_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class ArtifactProvenanceRow(Base):
    __tablename__ = "artifact_provenance"
    __table_args__ = (
        UniqueConstraint(
            "artifact_version_id",
            name="uq_artifact_provenance_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artifact_version_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    input_version_ids_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    provider_profile_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
    )
    model_id: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
        default="",
    )
    prompt_version: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="",
    )
    parameters_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    seed: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="",
    )
    task_attempt_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
    )
    operation_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        index=True,
    )
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class ArtifactFreshnessRow(Base):
    __tablename__ = "artifact_freshness"
    __table_args__ = (
        Index(
            "ix_artifact_freshness_project_status",
            "project_id",
            "status",
        ),
    )

    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="fresh",
        index=True,
    )
    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    stale_from_version_ids_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    detected_at: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
