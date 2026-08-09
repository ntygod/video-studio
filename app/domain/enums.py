from enum import StrEnum


class ProjectStage(StrEnum):
    BRIEF = "brief"
    BIBLE = "bible"
    NARRATIVE = "narrative"
    SHOTS = "shots"
    STORYBOARD = "storyboard"
    ANIMATIC = "animatic"
    EDIT = "edit"
    FINAL = "final"
    REVIEW = "review"


class ArtifactKind(StrEnum):
    BRIEF = "brief"
    PROJECT_BIBLE = "project_bible"
    CHARACTER_BIBLE = "character_bible"
    WORLD_BIBLE = "world_bible"
    STYLE_BIBLE = "style_bible"
    STORY_GRAPH = "story_graph"
    SHOT_PLAN = "shot_plan"
    EDIT_PLAN = "edit_plan"
    TIMELINE = "timeline"
    REVIEW_REPORT = "review_report"
    CUSTOM = "custom"


class ArtifactStatus(StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    LOCKED = "locked"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class AssetKind(StrEnum):
    REFERENCE = "reference"
    IMAGE = "image"
    VIDEO = "video"
    VOICE = "voice"
    MUSIC = "music"
    SFX = "sfx"
    SUBTITLE = "subtitle"
    DOCUMENT = "document"
    RENDER = "render"


class TrackKind(StrEnum):
    VIDEO = "video"
    IMAGE = "image"
    VOICE = "voice"
    MUSIC = "music"
    SFX = "sfx"
    SUBTITLE = "subtitle"
    GRAPHICS = "graphics"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ReviewGateStatus(StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    LOCKED = "locked"
