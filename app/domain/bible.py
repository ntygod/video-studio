from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VoiceProfile(DomainModel):
    provider_profile_id: str | None = None
    model: str = ""
    voice: str = ""
    speaking_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch: float = Field(default=0.0, ge=-1.0, le=1.0)
    supported_emotions: list[str] = Field(default_factory=list)


class CharacterBible(DomainModel):
    id: str
    name: str
    role: str = ""
    personality: str = ""
    appearance: str = ""
    wardrobe: list[str] = Field(default_factory=list)
    forbidden_traits: list[str] = Field(default_factory=list)
    reference_asset_ids: list[str] = Field(default_factory=list)
    voice: VoiceProfile = Field(default_factory=VoiceProfile)


class WorldBible(DomainModel):
    premise: str = ""
    era: str = ""
    locations: list[dict[str, Any]] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)


class StyleBible(DomainModel):
    visual_direction: str = ""
    color_palette: list[str] = Field(default_factory=list)
    lighting: str = ""
    camera_language: str = ""
    subtitle_style: dict[str, Any] = Field(default_factory=dict)
    sound_direction: str = ""
    negative_prompts: list[str] = Field(default_factory=list)


class ContinuityState(DomainModel):
    sequence_key: str = "default"
    character_states: dict[str, dict[str, Any]] = Field(default_factory=dict)
    world_state: dict[str, Any] = Field(default_factory=dict)
    unresolved_threads: list[str] = Field(default_factory=list)


class ProjectBible(DomainModel):
    logline: str = ""
    themes: list[str] = Field(default_factory=list)
    long_arc: str = ""
    characters: list[CharacterBible] = Field(default_factory=list)
    world: WorldBible = Field(default_factory=WorldBible)
    style: StyleBible = Field(default_factory=StyleBible)
    continuity: list[ContinuityState] = Field(default_factory=list)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
