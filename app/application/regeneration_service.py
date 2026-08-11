"""Prepare safe, selective regeneration of one generated Artifact."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.application.commands.base import CommandValidationError
from app.store.repositories import ConflictError, NotFoundError

_REGENERATION_INSTRUCTION = """

[重新生成约束]
这是对已有产物的选择性重新生成。context.current_inputs 是经过系统解析的最新输入，
必须以它为准；如果旧 context 中存在冲突内容，忽略旧内容。保持原产物类型和用途，
只修复由输入变化导致的内容差异。
""".strip()


def _source_job(uow, provenance: dict[str, Any]) -> dict[str, Any]:
    operation_id = str(provenance.get("operation_id") or "")
    if not operation_id:
        raise CommandValidationError(
            "Artifact 没有可重放的生成 Operation"
        )
    try:
        operation = uow.operations.get(operation_id)
    except NotFoundError as exc:
        raise CommandValidationError(
            "Artifact 的生成 Operation 已不存在"
        ) from exc
    if operation.get("actor_type") != "job":
        raise CommandValidationError(
            "Artifact 不是由可重放的生成任务创建"
        )
    job_id = str(operation.get("actor_id") or "")
    if not job_id:
        raise CommandValidationError(
            "Artifact 的生成任务引用无效"
        )
    try:
        job = uow.jobs.get(job_id)
    except NotFoundError as exc:
        raise CommandValidationError(
            "Artifact 的原始生成任务已不存在"
        ) from exc
    payload = job.get("payload") or {}
    capability = str(payload.get("capability") or "llm").lower()
    if job.get("job_type") not in {"generate", "llm"} or capability != "llm":
        raise CommandValidationError(
            "当前只支持重新生成有完整来源记录的 LLM Artifact"
        )
    if not str(payload.get("prompt") or "").strip():
        raise CommandValidationError(
            "原始生成任务没有可重放的 Prompt"
        )
    return job


def prepare_artifact_regeneration(
    uow,
    artifact_id: str,
) -> dict[str, Any]:
    """Build a new Job payload from exact provenance and current inputs.

    No mutation occurs here. The caller still creates the Job through
    ``CreateJobCommand``. A target version is captured so the eventual output
    cannot append to an Artifact that changed while the Job was running.
    """

    artifact = uow.artifacts.get(artifact_id)
    current = artifact.get("current_version") or {}
    current_version_id = str(current.get("id") or "")
    if not current_version_id:
        raise CommandValidationError(
            "Artifact 没有可重新生成的当前版本"
        )
    if current.get("status") == "locked":
        raise ConflictError(
            "已定稿 Artifact 不能追加重新生成版本"
        )

    freshness = uow.artifact_graph.get_freshness(artifact_id)
    if freshness["status"] == "blocked":
        raise ConflictError(
            "Artifact 的必需输入缺失，需先修复阻塞项"
        )
    if freshness["status"] != "stale":
        raise ConflictError(
            "只有已过期 Artifact 需要选择性重新生成"
        )

    provenance = uow.artifact_graph.provenance(
        current_version_id
    )
    if provenance is None:
        raise CommandValidationError(
            "Artifact 当前版本没有生成来源记录"
        )
    source_job = _source_job(uow, provenance)

    input_version_ids = [
        str(value)
        for value in provenance.get("input_version_ids") or []
        if str(value)
    ]
    if not input_version_ids:
        raise CommandValidationError(
            "Artifact 没有可刷新的上游版本输入"
        )

    refreshed_ids: list[str] = []
    current_inputs: list[dict[str, Any]] = []
    for previous_version_id in input_version_ids:
        try:
            previous_version = uow.artifacts.get_version(
                previous_version_id
            )
            upstream = uow.artifacts.get(
                previous_version["artifact_id"]
            )
        except NotFoundError as exc:
            raise ConflictError(
                "上游 Artifact 已删除，无法重新生成"
            ) from exc

        upstream_freshness = uow.artifact_graph.get_freshness(
            upstream["id"]
        )
        if upstream_freshness["status"] != "fresh":
            raise ConflictError(
                f"上游 Artifact {upstream['name']} 尚未恢复为最新状态"
            )
        upstream_version_id = str(
            upstream.get("current_version_id") or ""
        )
        if not upstream_version_id:
            raise ConflictError(
                f"上游 Artifact {upstream['name']} 没有当前版本"
            )
        upstream_version = uow.artifacts.get_version(
            upstream_version_id
        )
        refreshed_ids.append(upstream_version_id)
        current_inputs.append(
            {
                "artifact_id": upstream["id"],
                "artifact_name": upstream["name"],
                "artifact_kind": upstream["kind"],
                "version_id": upstream_version_id,
                "payload": deepcopy(
                    upstream_version.get("payload") or {}
                ),
            }
        )

    source_payload = deepcopy(source_job.get("payload") or {})
    source_context = source_payload.get("context")
    context = (
        deepcopy(source_context)
        if isinstance(source_context, dict)
        else {}
    )
    context["current_inputs"] = current_inputs
    context["regeneration"] = {
        "target_artifact_id": artifact_id,
        "previous_version_id": current_version_id,
        "source_job_id": source_job["id"],
    }

    prompt = str(source_payload.get("prompt") or "").rstrip()
    prompt_version = str(
        provenance.get("prompt_version")
        or source_payload.get("prompt_version")
        or "inline@1"
    )
    source_payload.update(
        {
            "unit_id": artifact.get("unit_id"),
            "capability": "llm",
            "prompt": f"{prompt}\n\n{_REGENERATION_INSTRUCTION}",
            "prompt_version": f"{prompt_version}+regenerate@1",
            "schema_id": artifact.get("schema_id") or "freeform",
            "artifact_kind": artifact["kind"],
            "artifact_name": artifact["name"],
            "context": context,
            "parameters": deepcopy(
                provenance.get("parameters")
                or source_payload.get("parameters")
                or {}
            ),
            "input_version_ids": refreshed_ids,
            "target_artifact_id": artifact_id,
            "expected_target_version_id": current_version_id,
            "_regeneration_source_job_id": source_job["id"],
            "_regeneration_of_version_id": current_version_id,
        }
    )
    source_payload.pop("_request_id", None)

    return {
        "project_id": artifact["project_id"],
        "unit_id": artifact.get("unit_id"),
        "artifact_id": artifact_id,
        "expected_target_version_id": current_version_id,
        "source_job_id": source_job["id"],
        "payload": source_payload,
    }


__all__ = ["prepare_artifact_regeneration"]
