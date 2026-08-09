from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import TrackKind


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimeRange(DomainModel):
    start: float = Field(default=0.0, ge=0.0)
    duration: float = Field(gt=0.0)


class Keyframe(DomainModel):
    time: float = Field(ge=0.0)
    property: str
    value: Any
    easing: str = "linear"


class Clip(DomainModel):
    id: str
    asset_id: str | None = None
    shot_id: str | None = None
    range: TimeRange
    source_in: float = Field(default=0.0, ge=0.0)
    speed: float = Field(default=1.0, ge=0.1, le=8.0)
    volume_db: float = Field(default=0.0, ge=-60.0, le=12.0)
    keyframes: list[Keyframe] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Track(DomainModel):
    id: str
    kind: TrackKind
    name: str = ""
    clips: list[Clip] = Field(default_factory=list)
    muted: bool = False
    locked: bool = False


class TimelineIR(DomainModel):
    width: int = Field(default=1080, ge=2)
    height: int = Field(default=1920, ge=2)
    fps: int = Field(default=30, ge=1, le=120)
    tracks: list[Track] = Field(default_factory=list)
    duration: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def derive_duration(self):
        end = 0.0
        for track in self.tracks:
            for clip in track.clips:
                end = max(end, clip.range.start + clip.range.duration)
        if self.duration < end:
            self.duration = end
        return self

