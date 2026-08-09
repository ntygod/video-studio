from pydantic import BaseModel, ConfigDict, Field

class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Audience(DomainModel):
    description: str = "普通大众"
    age_range: str = ""
    knowledge_level: str = "general"
    interests: list[str] = Field(default_factory=list)


class PlatformTarget(DomainModel):
    platform: str
    aspect_ratio: str = ""
    target_seconds: int | None = Field(default=None, ge=1, le=604800)
    language: str = "zh-CN"


class Constraint(DomainModel):
    kind: str
    value: str
    required: bool = True


class CreativeBrief(DomainModel):
    title: str = "未命名项目"
    concept: str = ""
    objective: str = ""
    format_id: str = "freeform"
    format_notes: str = ""
    audience: Audience = Field(default_factory=Audience)
    platforms: list[PlatformTarget] = Field(default_factory=list)
    tone: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    custom_fields: dict = Field(default_factory=dict)
    approved: bool = False
