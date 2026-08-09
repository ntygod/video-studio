from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TransitionDecision(DomainModel):
    kind: str = "cut"
    duration: float = Field(default=0.0, ge=0.0, le=10.0)
    reason: str = ""


class AudioDecision(DomainModel):
    music_action: str = "continue"
    duck_db: float = Field(default=-9.0, ge=-60.0, le=0.0)
    sfx_asset_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class EditDecision(DomainModel):
    id: str
    shot_id: str
    asset_id: str | None = None
    source_in: float = Field(default=0.0, ge=0.0)
    source_out: float | None = Field(default=None, ge=0.0)
    duration: float = Field(default=1.0, gt=0.0)
    speed: float = Field(default=1.0, ge=0.1, le=8.0)
    hold_after: float = Field(default=0.0, ge=0.0, le=30.0)
    transition_in: TransitionDecision = Field(default_factory=TransitionDecision)
    audio: AudioDecision = Field(default_factory=AudioDecision)
    reason: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class EditPlan(DomainModel):
    decisions: list[EditDecision] = Field(default_factory=list)
    target_seconds: float | None = Field(default=None, gt=0.0)
    editorial_notes: list[str] = Field(default_factory=list)

