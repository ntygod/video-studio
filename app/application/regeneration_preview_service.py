"""Read-only, deterministic preview of a selective regeneration cascade."""

from __future__ import annotations

import heapq
from collections import defaultdict, deque
from typing import Any, Iterable

from sqlalchemy import select

from app.application.commands.base import CommandValidationError
from app.application.regeneration_service import _source_job
from app.store.dependency_models import ArtifactDependencyRow
from app.store.models import ArtifactRow, ArtifactVersionRow
from app.store.repositories import ConflictError, NotFoundError

MAX_REGENERATION_PREVIEW_ARTIFACTS = 500
_AUTOMATED_ACTIONS = frozenset(
    {"regenerate_llm", "recompile_timeline"}
)


def _add_blocker(
    blockers: list[dict[str, Any]],
    code: str,
    message: str,
    *,
    entity_type: str = "",
    entity_id: str = "",
) -> None:
    key = (code, entity_type, entity_id)
    if any(
        (
            item["code"],
            item.get("entity_type", ""),
            item.get("entity_id", ""),
        )
        == key
        for item in blockers
    ):
        return
    item: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if entity_type:
        item["entity_type"] = entity_type
    if entity_id:
        item["entity_id"] = entity_id
    blockers.append(item)


def _project_graph(
    uow,
    project_id: str,
) -> tuple[
    dict[str, ArtifactRow],
    dict[str, set[str]],
    dict[str, set[str]],
]:
    artifacts = uow.session.scalars(
        select(ArtifactRow).where(
            ArtifactRow.project_id == project_id
        )
    ).all()
    by_id = {row.id: row for row in artifacts}
    downstream: dict[str, set[str]] = defaultdict(set)
    upstream: dict[str, set[str]] = defaultdict(set)
    rows = uow.session.execute(
        select(
            ArtifactDependencyRow,
            ArtifactVersionRow.artifact_id,
        )
        .join(
            ArtifactVersionRow,
            ArtifactDependencyRow.upstream_version_id
            == ArtifactVersionRow.id,
        )
        .where(ArtifactDependencyRow.project_id == project_id)
    ).all()
    for edge, upstream_artifact_id in rows:
        target = by_id.get(edge.downstream_artifact_id)
        if (
            target is None
            or target.current_version_id
            != edge.downstream_version_id
        ):
            continue
        source_id = str(upstream_artifact_id)
        target_id = str(edge.downstream_artifact_id)
        if source_id not in by_id or source_id == target_id:
            continue
        downstream[source_id].add(target_id)
        upstream[target_id].add(source_id)
    return by_id, downstream, upstream


def _selected_artifacts(
    roots: list[str],
    downstream: dict[str, set[str]],
    *,
    include_downstream: bool,
) -> tuple[set[str], dict[str, int]]:
    selected = set(roots)
    depth = {artifact_id: 0 for artifact_id in roots}
    if not include_downstream:
        return selected, depth

    queue: deque[str] = deque(roots)
    while queue:
        current = queue.popleft()
        next_depth = depth[current] + 1
        for target in sorted(downstream.get(current, set())):
            if target in selected:
                depth[target] = min(depth.get(target, next_depth), next_depth)
                continue
            selected.add(target)
            depth[target] = next_depth
            if len(selected) > MAX_REGENERATION_PREVIEW_ARTIFACTS:
                raise ConflictError(
                    "regeneration preview exceeds the 500 Artifact safety limit"
                )
            queue.append(target)
    return selected, depth


def _topological_order(
    selected: set[str],
    artifacts: dict[str, ArtifactRow],
    downstream: dict[str, set[str]],
    upstream: dict[str, set[str]],
    depth: dict[str, int],
) -> list[str]:
    indegree = {
        artifact_id: len(upstream.get(artifact_id, set()) & selected)
        for artifact_id in selected
    }
    heap: list[tuple[int, str, str]] = []
    for artifact_id, count in indegree.items():
        if count == 0:
            artifact = artifacts[artifact_id]
            heapq.heappush(
                heap,
                (
                    depth.get(artifact_id, 0),
                    str(artifact.name or ""),
                    artifact_id,
                ),
            )

    result: list[str] = []
    while heap:
        _depth, _name, artifact_id = heapq.heappop(heap)
        result.append(artifact_id)
        for target in sorted(downstream.get(artifact_id, set()) & selected):
            indegree[target] -= 1
            if indegree[target] == 0:
                artifact = artifacts[target]
                heapq.heappush(
                    heap,
                    (
                        depth.get(target, 0),
                        str(artifact.name or ""),
                        target,
                    ),
                )
    if len(result) != len(selected):
        raise ConflictError(
            "selected Artifact dependency graph contains a cycle"
        )
    return result


def _inspect_exact_inputs(
    uow,
    project_id: str,
    provenance: dict[str, Any],
    selected: set[str],
    depends_on: set[str],
    blockers: list[dict[str, Any]],
) -> None:
    input_ids = [
        str(value)
        for value in provenance.get("input_version_ids") or []
        if str(value)
    ]
    if not input_ids:
        _add_blocker(
            blockers,
            "no_refreshable_inputs",
            "Artifact has no exact upstream version inputs to refresh.",
        )
        return

    for version_id in input_ids:
        try:
            version = uow.artifacts.get_version(version_id)
            upstream = uow.artifacts.get(version["artifact_id"])
        except NotFoundError:
            _add_blocker(
                blockers,
                "upstream_version_missing",
                f"Required upstream version no longer exists: {version_id}",
                entity_type="artifact_version",
                entity_id=version_id,
            )
            continue
        if upstream["project_id"] != project_id:
            _add_blocker(
                blockers,
                "upstream_cross_project",
                "A required upstream Artifact belongs to another project.",
                entity_type="artifact",
                entity_id=upstream["id"],
            )
            continue
        if not upstream.get("current_version_id"):
            _add_blocker(
                blockers,
                "upstream_has_no_current_version",
                f"Upstream Artifact has no current version: {upstream['name']}",
                entity_type="artifact",
                entity_id=upstream["id"],
            )
            continue
        freshness = uow.artifact_graph.get_freshness(upstream["id"])
        if upstream["id"] in selected:
            depends_on.add(upstream["id"])
        elif freshness["status"] != "fresh":
            _add_blocker(
                blockers,
                "external_upstream_not_fresh",
                (
                    f"Upstream Artifact is {freshness['status']} and is not "
                    f"included in this preview: {upstream['name']}"
                ),
                entity_type="artifact",
                entity_id=upstream["id"],
            )


def _inspect_external_graph_inputs(
    uow,
    external_upstreams: Iterable[str],
    blockers: list[dict[str, Any]],
) -> None:
    for upstream_id in sorted(set(external_upstreams)):
        upstream = uow.artifacts.get(upstream_id)
        freshness = uow.artifact_graph.get_freshness(upstream_id)
        if freshness["status"] == "fresh":
            continue
        _add_blocker(
            blockers,
            "external_upstream_not_fresh",
            (
                f"Upstream Artifact is {freshness['status']} and is not "
                f"included in this preview: {upstream['name']}"
            ),
            entity_type="artifact",
            entity_id=upstream_id,
        )


def _local_step(
    uow,
    project_id: str,
    artifact_id: str,
    selected: set[str],
    graph_upstream: dict[str, set[str]],
) -> dict[str, Any]:
    artifact = uow.artifacts.get(artifact_id)
    current = artifact.get("current_version") or {}
    current_version_id = str(current.get("id") or "")
    freshness = uow.artifact_graph.get_freshness(artifact_id)
    status = str(freshness["status"])
    depends_on = set(graph_upstream.get(artifact_id, set()) & selected)
    external_upstreams = graph_upstream.get(artifact_id, set()) - selected
    blockers: list[dict[str, Any]] = []
    source_job_id: str | None = None
    direct_missing_assets: list[str] = []

    if current_version_id:
        direct_missing_assets = sorted(
            {
                str(item["upstream_asset_id"])
                for item in (
                    uow.artifact_graph.asset_dependencies_for_version(
                        current_version_id
                    )
                )
                if not item.get("asset_exists")
            }
        )

    if status == "fresh":
        action = "none"
        state = "skipped"
        local_automatable = False
    elif status == "needs_review":
        action = "review"
        state = "requires_review"
        local_automatable = False
    elif not current_version_id:
        action = "manual"
        state = "manual"
        local_automatable = False
        _add_blocker(
            blockers,
            "no_current_version",
            "Artifact has no current version.",
        )
    elif direct_missing_assets:
        if artifact["kind"] == "timeline":
            action = "repair_timeline_assets"
            state = "requires_input"
            local_automatable = False
            _add_blocker(
                blockers,
                "asset_replacements_required",
                "Every missing Timeline Asset needs an explicit replacement.",
            )
        else:
            action = "manual"
            state = "manual"
            local_automatable = False
            _add_blocker(
                blockers,
                "required_assets_missing",
                "Required Asset inputs are missing and no automatic repair is defined.",
            )
    elif artifact["kind"] == "timeline" and status in {
        "stale",
        "blocked",
    }:
        action = "recompile_timeline"
        state = "ready"
        local_automatable = True
        provenance = uow.artifact_graph.provenance(current_version_id)
        if provenance:
            _inspect_exact_inputs(
                uow,
                project_id,
                provenance,
                selected,
                depends_on,
                blockers,
            )
        _inspect_external_graph_inputs(
            uow,
            external_upstreams,
            blockers,
        )
    elif status in {"stale", "blocked"}:
        action = "regenerate_llm"
        state = "ready"
        local_automatable = True
        provenance = uow.artifact_graph.provenance(current_version_id)
        if provenance is None:
            _add_blocker(
                blockers,
                "provenance_missing",
                "Current Artifact version has no generation provenance.",
            )
        else:
            try:
                source_job = _source_job(uow, provenance)
                source_job_id = str(source_job["id"])
            except (CommandValidationError, ConflictError) as exc:
                _add_blocker(
                    blockers,
                    "source_not_replayable",
                    str(exc),
                )
            _inspect_exact_inputs(
                uow,
                project_id,
                provenance,
                selected,
                depends_on,
                blockers,
            )
        _inspect_external_graph_inputs(
            uow,
            external_upstreams,
            blockers,
        )
    else:
        action = "manual"
        state = "manual"
        local_automatable = False
        _add_blocker(
            blockers,
            "unsupported_freshness_state",
            f"No repair action is defined for Freshness state {status}.",
        )

    if (
        status not in {"fresh", "needs_review"}
        and current.get("status") == "locked"
    ):
        _add_blocker(
            blockers,
            "current_version_locked",
            "The current version is locked and cannot receive a repair version.",
            entity_type="artifact_version",
            entity_id=current_version_id,
        )
        state = "blocked"

    if blockers and state == "ready":
        state = "blocked"

    return {
        "artifact_id": artifact_id,
        "artifact_kind": artifact["kind"],
        "artifact_name": artifact["name"],
        "unit_id": artifact.get("unit_id"),
        "current_version_id": current_version_id or None,
        "expected_current_version_id": current_version_id or None,
        "freshness": freshness,
        "action": action,
        "execution_state": state,
        "depends_on": sorted(depends_on),
        "external_upstream_artifact_ids": sorted(external_upstreams),
        "missing_asset_ids": sorted(
            set(freshness.get("blocked_by_asset_ids") or [])
        ),
        "direct_missing_asset_ids": direct_missing_assets,
        "source_job_id": source_job_id,
        "blockers": blockers,
        "_local_automatable": local_automatable,
    }


def preview_regeneration_cascade(
    uow,
    project_id: str,
    artifact_ids: list[str],
    *,
    include_downstream: bool = True,
) -> dict[str, Any]:
    """Preview a repair cascade without creating Jobs or Operations."""

    uow.projects.get(project_id)
    roots = list(
        dict.fromkeys(
            str(artifact_id)
            for artifact_id in artifact_ids
            if str(artifact_id)
        )
    )
    if not roots:
        raise CommandValidationError(
            "regeneration preview requires at least one Artifact"
        )
    if len(roots) > MAX_REGENERATION_PREVIEW_ARTIFACTS:
        raise ConflictError(
            "regeneration preview exceeds the 500 Artifact safety limit"
        )

    artifacts, downstream, upstream = _project_graph(uow, project_id)
    for artifact_id in roots:
        if artifact_id not in artifacts:
            raise NotFoundError(artifact_id)

    selected, depth = _selected_artifacts(
        roots,
        downstream,
        include_downstream=include_downstream,
    )
    order = _topological_order(
        selected,
        artifacts,
        downstream,
        upstream,
        depth,
    )

    steps_by_id = {
        artifact_id: _local_step(
            uow,
            project_id,
            artifact_id,
            selected,
            upstream,
        )
        for artifact_id in order
    }
    available_after_plan: dict[str, bool] = {}
    steps: list[dict[str, Any]] = []
    for artifact_id in order:
        step = steps_by_id[artifact_id]
        predecessors = step["depends_on"]
        unresolved = [
            predecessor
            for predecessor in predecessors
            if not available_after_plan.get(predecessor, False)
        ]
        predecessor_changes = [
            predecessor
            for predecessor in predecessors
            if steps_by_id[predecessor]["freshness"]["status"]
            != "fresh"
        ]

        if step["execution_state"] == "skipped":
            available = True
        elif (
            step["_local_automatable"]
            and not step["blockers"]
        ):
            if unresolved:
                for predecessor in unresolved:
                    _add_blocker(
                        step["blockers"],
                        "predecessor_not_resolvable",
                        "A required predecessor cannot be resolved by this preview.",
                        entity_type="artifact",
                        entity_id=predecessor,
                    )
                step["execution_state"] = "blocked"
                available = False
            else:
                step["execution_state"] = (
                    "waiting_for_predecessors"
                    if predecessor_changes
                    else "ready"
                )
                available = True
        else:
            available = False

        step["can_execute_automatically"] = (
            step["execution_state"]
            in {"ready", "waiting_for_predecessors"}
            and step["action"] in _AUTOMATED_ACTIONS
        )
        step["available_after_plan"] = available
        available_after_plan[artifact_id] = available
        step.pop("_local_automatable", None)
        steps.append(step)

    states: dict[str, int] = defaultdict(int)
    for step in steps:
        states[str(step["execution_state"])] += 1
    summary = {
        "total": len(steps),
        "automatable": sum(
            1 for step in steps if step["can_execute_automatically"]
        ),
        "ready": states["ready"],
        "waiting_for_predecessors": states[
            "waiting_for_predecessors"
        ],
        "requires_input": states["requires_input"],
        "requires_review": states["requires_review"],
        "manual": states["manual"],
        "blocked": states["blocked"],
        "skipped": states["skipped"],
    }
    return {
        "project_id": project_id,
        "root_artifact_ids": roots,
        "include_downstream": include_downstream,
        "order": order,
        "summary": summary,
        "steps": steps,
    }


__all__ = [
    "MAX_REGENERATION_PREVIEW_ARTIFACTS",
    "preview_regeneration_cascade",
]
