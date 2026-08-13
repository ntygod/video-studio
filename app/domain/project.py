from pydantic import BaseModel, ConfigDict, Field

from typing import Any, Literal

from .bible import ProjectBible
from .brief import CreativeBrief


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeliveryProfile(DomainModel):
    name: str
    platform: str
    aspect_ratio: str = ""
    resolution: str = ""
    fps: int = Field(default=30, ge=1, le=120)
    max_seconds: int | None = Field(default=None, ge=1)
    burned_subtitles: bool = False


class RuntimeCostPolicy(DomainModel):
    """Project defaults frozen into each new durable RuntimePlan."""

    unpriced_provider_mode: Literal["allow", "block"] = "allow"


class ProjectSettings(DomainModel):
    quality_mode: str = "draft"
    default_language: str = "zh-CN"
    delivery_profiles: list[DeliveryProfile] = Field(default_factory=list)
    provider_overrides: dict[str, str] = Field(default_factory=dict)
    pinned_refs: list[dict[str, str]] = Field(default_factory=list)
    runtime_cost_policy: RuntimeCostPolicy = Field(
        default_factory=RuntimeCostPolicy
    )


class CreativeProject(DomainModel):
    id: str
    title: str
    project_type: str = "freeform"
    workflow_id: str = "freeform"
    stage: str = "brief"
    brief: CreativeBrief
    bible: ProjectBible = Field(default_factory=ProjectBible)
    settings: ProjectSettings = Field(default_factory=ProjectSettings)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    revision: int = 1
    created_at: float
    updated_at: float


class CreativeUnit(DomainModel):
    id: str
    project_id: str
    parent_id: str | None = None
    unit_type: str = "unit"
    order_index: float = 0.0
    title: str
    summary: str = ""
    stage: str = "brief"
    continuity_summary: str = ""
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    created_at: float
    updated_at: float
