from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.domain import CreativeBrief, ProjectBible
from app.domain.enums import ArtifactStatus, ProposalStatus
from app.application.structure import (
    apply_structure_changes,
    preview_structure_changes,
)
from app.store.repositories import ConflictError

#: 结构提案不产生 artifact，直接改 creative_units。
STRUCTURE_KIND = "structure"


def _selected_changes(
    proposal: dict[str, Any], op_indices: list[int] | None
) -> list[dict[str, Any]]:
    changes = proposal.get("operations") or []
    if op_indices is None:
        return list(changes)
    selected = [changes[index] for index in op_indices]
    if not selected:
        raise ValueError("至少选择一条 operation")
    return selected


def _tokens(path: str) -> list[str]:
    if not path.startswith("/"):
        raise ValueError("patch path must start with /")
    if path == "/":
        return []
    return [token.replace("~1", "/").replace("~0", "~") for token in path[1:].split("/")]


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """dict 递归合并；list 与标量整体替换（修 D1）。"""
    result = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _diff_payloads(
    before: dict[str, Any], after: dict[str, Any], prefix: str = ""
) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    for key in sorted(set(before) | set(after)):
        path = f"{prefix}/{key}"
        if key not in before:
            diffs.append({"path": path, "op": "add", "before": None, "after": after[key]})
        elif key not in after:
            diffs.append({"path": path, "op": "remove", "before": before[key], "after": None})
        elif isinstance(before[key], dict) and isinstance(after[key], dict):
            diffs.extend(_diff_payloads(before[key], after[key], path))
        elif before[key] != after[key]:
            diffs.append(
                {"path": path, "op": "replace", "before": before[key], "after": after[key]}
            )
    return diffs


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


def _proposed_payload(
    proposal: dict[str, Any],
    current_payload: dict[str, Any],
    op_indices: list[int] | None,
) -> dict[str, Any]:
    if op_indices is not None:
        return apply_operations(current_payload, _selected_changes(proposal, op_indices))
    if proposal.get("proposed_payload") is not None:
        return deepcopy(proposal["proposed_payload"])
    return apply_operations(current_payload, proposal.get("operations") or [])


def preview_proposal(uow, proposal_id: str) -> dict[str, Any]:
    proposal = uow.proposals.get(proposal_id)
    if proposal["artifact_kind"] == STRUCTURE_KIND:
        # 结构提案改的是单元树，没有 payload 可 diff。
        preview = preview_structure_changes(
            uow, proposal["project_id"], proposal.get("operations") or []
        )
        return {"before": {}, "after": {}, "field_diffs": [], **preview}
    artifact = (
        uow.artifacts.get(proposal["artifact_id"]) if proposal.get("artifact_id") else None
    )
    before = (artifact.get("current_version") or {}).get("payload") or {} if artifact else {}
    after = _proposed_payload(proposal, before, None)
    if proposal["artifact_kind"] in ("brief", "project_bible"):
        after = deep_merge(before, after)
    return {
        "before": before,
        "after": after,
        "field_diffs": _diff_payloads(before, after),
    }


def accept_proposal(
    uow, proposal_id: str, op_indices: list[int] | None = None
) -> dict[str, Any]:
    proposal = uow.proposals.get(proposal_id)
    if proposal["status"] != ProposalStatus.PENDING.value:
        raise ConflictError(f"proposal already {proposal['status']}")

    if proposal["artifact_kind"] == STRUCTURE_KIND:
        # 结构提案直接落到 creative_units，不新建 artifact。
        applied = apply_structure_changes(
            uow, proposal["project_id"], _selected_changes(proposal, op_indices)
        )
        accepted = uow.proposals.set_status(proposal_id, ProposalStatus.ACCEPTED.value)
        return {
            "proposal": accepted,
            "artifact_id": None,
            "version": None,
            "applied": applied,
        }

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
    proposed_payload = _proposed_payload(
        proposal, current.get("payload") or {}, op_indices
    )
    if proposal["artifact_kind"] in ("brief", "project_bible"):
        proposed_payload = deep_merge(current.get("payload") or {}, proposed_payload)
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

