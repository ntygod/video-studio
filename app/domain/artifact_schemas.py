"""Schemas that are specific to versioned Artifact payloads.

These models intentionally validate structure rather than creative quality.
Completeness, continuity and production readiness belong to Evaluators in a
later layer; the registry only guarantees that a known payload has a stable
machine-readable shape.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScreenplayLine(DomainModel):
    type: Literal[
        "action",
        "dialogue",
        "parenthetical",
        "transition",
        "note",
    ] = "action"
    text: str = Field(min_length=1)
    character_id: str | None = None
    emotion: str = ""
    beat_id: str | None = None

    @model_validator(mode="after")
    def dialogue_requires_character(self):
        if self.type == "dialogue" and not self.character_id:
            raise ValueError("dialogue line requires character_id")
        return self


class ScreenplayScene(DomainModel):
    id: str = Field(min_length=1)
    heading: str = ""
    location: str = ""
    time_of_day: str = ""
    purpose: str = ""
    summary: str = ""
    character_ids: list[str] = Field(default_factory=list)
    lines: list[ScreenplayLine] = Field(default_factory=list)


class Screenplay(DomainModel):
    title: str = ""
    logline: str = ""
    scenes: list[ScreenplayScene] = Field(default_factory=list)
