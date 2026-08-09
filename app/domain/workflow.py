from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowNode(DomainModel):
    key: str
    label: str = ""
    kind: str = "llm"
    description: str = ""
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    required_capability: str = "llm"
    schema_id: str = "freeform"
    prompt: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    retry_policy: dict[str, Any] = Field(default_factory=dict)


class WorkflowEdge(DomainModel):
    source: str
    target: str
    condition: str = ""
    outputs: list[str] = Field(default_factory=list)


class WorkflowDefinition(DomainModel):
    id: str
    name: str
    description: str = ""
    version: str = "1"
    entry_nodes: list[str] = Field(default_factory=list)
    nodes: dict[str, WorkflowNode] = Field(default_factory=dict)
    edges: list[WorkflowEdge] = Field(default_factory=list)
    global_parameters: dict[str, Any] = Field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0
