from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CameraSpec(DomainModel):
    shot_size: str = "medium"
    angle: str = "eye_level"
    movement: str = "static"
    lens: str = ""


class CompositionSpec(DomainModel):
    subject: str = ""
    foreground: str = ""
    background: str = ""
    lighting: str = ""
    color_notes: str = ""


class GenerationRequest(DomainModel):
    prompt: str = ""
    negative_prompt: str = ""
    model_profile_id: str | None = None
    aspect_ratio: str = ""
    resolution: str = ""
    duration_seconds: float | None = Field(default=None, ge=0.1, le=120.0)
    reference_asset_ids: list[str] = Field(default_factory=list)
    parameters: dict = Field(default_factory=dict)


class Shot(DomainModel):
    id: str
    scene_id: str
    beat_id: str | None = None
    purpose: str = ""
    character_ids: list[str] = Field(default_factory=list)
    action: str = ""
    camera: CameraSpec = Field(default_factory=CameraSpec)
    composition: CompositionSpec = Field(default_factory=CompositionSpec)
    dialogue_line_ids: list[str] = Field(default_factory=list)
    duration_policy: str = "content_driven"
    duration_hint: float | None = Field(default=None, ge=0.1, le=120.0)
    generation: GenerationRequest = Field(default_factory=GenerationRequest)


class ShotPlan(DomainModel):
    shots: list[Shot] = Field(default_factory=list)
