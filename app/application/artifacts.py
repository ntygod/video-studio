from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.domain import CreativeBrief, ProjectBible
from app.domain.enums import ArtifactStatus, ProposalStatus
from app.store.repositories import ConflictError


def _tokens(path: str) -> list[str]:
    if not path.startswith("/"):
        raise ValueError("patch path must start with /")
    if path == "/":
        return []
    return [token.replace("~1", "/").replace("~0", "~") for token in path[1:].split("/")]


def apply_operations(payload: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    result = deepcopy(payload)
    for operation in operations:
        op = operation.get("op")
        tokens = _tokens(operation.get("path", ""))
        if not tokens:
            if op == "remove":
                result = {}
            elif op in ("add", "replace"):
                value = operation.get("value")
                if not isinstance(value, dict):
                    raise ValueError("root artifact payload must be an object")
                result = deepcopy(value)
            continue
        cursor: Any = result
        for token in tokens[:-1]:
            if isinstance(cursor, list):
                cursor = cursor[int(token)]
            else:
                if token not in cursor or not isinstance(cursor[token], (dict, list)):
                    cursor[token] = {}
                cursor = cursor[token]
        key = tokens[-1]
        if isinstance(cursor, list):
            index = len(cursor) if key == "-" else int(key)
            if op == "remove":
                cursor.pop(index)
            elif op == "add":
                cursor.insert(index, deepcopy(operation.get("value")))
            elif op == "replace":
                cursor[index] = deepcopy(operation.get("value"))
        else:
            if op == "remove":
                cursor.pop(key, None)
            elif op in ("add", "replace"):
                cursor[key] = deepcopy(operation.get("value"))
            else:
                raise ValueError(f"unsupported patch operation: {op}")
    return result


def accept_proposal(uow, proposal_id: str) -> dict[str, Any]:
    proposal = uow.proposals.get(proposal_id)
    if proposal["status"] != ProposalStatus.PENDING.value:
        raise ConflictError(f"proposal already {proposal['status']}")
    artifact_id = proposal.get("artifact_id")
    if artifact_id:
        artifact = uow.artifacts.get(artifact_id)
    else:
        artifact = uow.artifacts.create(
            project_id=proposal["project_id"],
            unit_id=proposal.get("unit_id"),
            kind=proposal["artifact_kind"],
            name=proposal["title"],
            schema_id=f"custom/{proposal['artifact_kind']}@1",
            payload={},
            source="system",
        )
        artifact_id = artifact["id"]
    current = artifact.get("current_version") or {"payload": {}, "id": None}
    if proposal.get("base_version_id") and current.get("id") != proposal["base_version_id"]:
        raise ConflictError("artifact changed after proposal was created")
    proposed_payload = proposal.get("proposed_payload")
    if proposed_payload is None:
        proposed_payload = apply_operations(current.get("payload") or {}, proposal["operations"])
    version = uow.artifacts.add_version(
        artifact_id,
        proposed_payload,
        source="ai",
        status=ArtifactStatus.DRAFT.value,
        parent_version_id=current.get("id"),
        note=proposal["rationale"],
    )
    accepted = uow.proposals.set_status(proposal_id, ProposalStatus.ACCEPTED.value)

    if proposal["artifact_kind"] in ("brief", "project_bible"):
        project = uow.projects.get(proposal["project_id"])
        data = project.model_dump(mode="json")
        if proposal["artifact_kind"] == "brief":
            data["brief"] = CreativeBrief.model_validate(proposed_payload).model_dump(mode="json")
            data["title"] = data["brief"]["title"] or data["title"]
        else:
            data["bible"] = ProjectBible.model_validate(proposed_payload).model_dump(mode="json")
        uow.projects.update(
            type(project).model_validate(data), expected_revision=project.revision
        )
    return {"proposal": accepted, "artifact_id": artifact_id, "version": version}


def reject_proposal(uow, proposal_id: str) -> dict[str, Any]:
    return uow.proposals.set_status(proposal_id, ProposalStatus.REJECTED.value)

