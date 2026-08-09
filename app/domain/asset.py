from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import AssetKind


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerationMetadata(DomainModel):
    provider_profile_id: str | None = None
    model_profile_id: str | None = None
    prompt: str = ""
    negative_prompt: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None


class AssetCandidate(DomainModel):
    id: str
    uri: str
    mime_type: str
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    review_notes: list[str] = Field(default_factory=list)
    selected: bool = False


class Asset(DomainModel):
    id: str
    kind: AssetKind
    project_id: str
    unit_id: str | None = None
    shot_id: str | None = None
    name: str = ""
    uri: str = ""
    mime_type: str = "application/octet-stream"
    sha256: str = ""
    parent_asset_id: str | None = None
    generation: GenerationMetadata = Field(default_factory=GenerationMetadata)
    candidates: list[AssetCandidate] = Field(default_factory=list)
