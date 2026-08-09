from pydantic import BaseModel, ConfigDict, Field, model_validator


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DialogueLine(DomainModel):
    id: str
    speaker_id: str
    text: str
    emotion: str = "neutral"
    pace: float = Field(default=1.0, ge=0.5, le=2.0)
    pause_before: float = Field(default=0.0, ge=0.0, le=10.0)
    pause_after: float = Field(default=0.2, ge=0.0, le=10.0)
    overlap_with: str | None = None

    @model_validator(mode="after")
    def validate_overlap(self):
        if self.overlap_with == self.id:
            raise ValueError("dialogue line cannot overlap with itself")
        return self


class ActionCue(DomainModel):
    description: str
    duration_hint: float | None = Field(default=None, ge=0.1, le=120.0)
    sfx_tags: list[str] = Field(default_factory=list)


class Beat(DomainModel):
    id: str
    purpose: str
    summary: str = ""
    emotion: int = Field(default=5, ge=0, le=10)
    tempo: str = "medium"
    dialogue: list[DialogueLine] = Field(default_factory=list)
    actions: list[ActionCue] = Field(default_factory=list)


class Scene(DomainModel):
    id: str
    title: str = ""
    location: str = ""
    time_of_day: str = ""
    purpose: str = ""
    character_ids: list[str] = Field(default_factory=list)
    beats: list[Beat] = Field(default_factory=list)


class Act(DomainModel):
    id: str
    title: str = ""
    purpose: str = ""
    scenes: list[Scene] = Field(default_factory=list)


class StoryGraph(DomainModel):
    title: str = ""
    logline: str = ""
    acts: list[Act] = Field(default_factory=list)
    open_threads: list[str] = Field(default_factory=list)

