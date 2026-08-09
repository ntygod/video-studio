from __future__ import annotations

import json
import threading
from typing import Any

from app.integrations.llm import LLMClient
from app.integrations.media import generate_image, generate_video
from app.store import UnitOfWork


class JobEngine:
    def __init__(self, database, settings, media_store=None):
        self.database = database
        self.settings = settings
        self.media_store = media_store
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def submit(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._threads:
                return
            thread = threading.Thread(
                target=self._run,
                args=(job_id,),
                name=f"job-{job_id[:8]}",
                daemon=True,
            )
            self._threads[job_id] = thread
            thread.start()

    def recover(self) -> int:
        count = 0
        with UnitOfWork(self.database) as uow:
            jobs = uow.jobs.list()
        for job in jobs:
            if job["status"] in ("queued", "running"):
                count += 1
                self.submit(job["id"])
        return count

    def _run(self, job_id: str) -> None:
        try:
            with UnitOfWork(self.database) as uow:
                uow.jobs.update_state(job_id, "running", progress=0.0)
                uow.jobs.add_event(job_id, "任务开始执行", stage="start")
            self._execute(job_id)
            with UnitOfWork(self.database) as uow:
                uow.jobs.add_event(job_id, "任务执行完成", stage="end", progress=100.0)
                uow.jobs.update_state(job_id, "succeeded", progress=100.0)
        except Exception as exc:
            with UnitOfWork(self.database) as uow:
                uow.jobs.add_event(job_id, f"任务失败：{exc}", level="error", stage="error")
                uow.jobs.update_state(job_id, "failed", error=str(exc))
        finally:
            with self._lock:
                self._threads.pop(job_id, None)

    def _execute(self, job_id: str) -> None:
        with UnitOfWork(self.database) as uow:
            job = uow.jobs.get(job_id)
            if job["cancel_requested"]:
                uow.jobs.update_state(job_id, "canceled")
                uow.jobs.add_event(job_id, "任务已取消", level="warning", stage="cancel")
                return
            payload = job.get("payload") or {}
            node_key = payload.get("node_key") or job["job_type"]
            input_hash = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            node_run = uow.jobs.create_node_run(job_id, node_key, input_hash)
            node_run_id = node_run["id"]
            job_type = job["job_type"]
            provider_capability = payload.get("capability") or "llm"

        if job_type == "voice_synthesis":
            self._run_voice_synthesis(job_id, node_run_id, payload)
        elif job_type == "llm" or provider_capability == "llm":
            self._run_llm(job_id, node_run_id, payload)
        elif provider_capability in ("image", "video"):
            self._run_media(job_id, node_run_id, payload, provider_capability)
        elif provider_capability == "tts":
            self._run_tts(job_id, node_run_id, payload)
        elif job_type == "render":
            self._run_render(job_id, node_run_id, payload)
        elif job_type == "workflow":
            self._run_workflow(job_id, node_run_id, payload)
        else:
            raise ValueError(f"unknown job type: {job_type}")


    def _run_llm(self, job_id: str, node_run_id: str, payload: dict[str, Any]) -> None:
        with UnitOfWork(self.database) as uow:
            job = uow.jobs.get(job_id)
            prompt = str(payload.get("prompt") or "")
            schema_id = str(payload.get("schema_id") or "freeform")
            provider = self._provider(uow, "llm")
            project_id = job["project_id"]
            unit_id = job["unit_id"]
            artifact_kind = payload.get("artifact_kind") or "generated"
            artifact_name = payload.get("artifact_name") or "AI 生成"
        messages = [{"role": "system", "content": prompt}]
        context = payload.get("context") or {}
        messages.append({"role": "user", "content": json.dumps(context, ensure_ascii=False)})
        response = LLMClient(provider).chat_json(messages)
        with UnitOfWork(self.database) as uow:
            artifact = uow.artifacts.create(
                project_id=project_id,
                unit_id=unit_id,
                kind=artifact_kind,
                name=artifact_name,
                schema_id=schema_id,
                payload=response,
                source="job",
            )
            uow.jobs.update_state(
                job_id,
                "running",
                progress=80.0,
                result={"artifact_id": artifact["id"], "payload": response},
            )
            uow.jobs.add_event(job_id, f"已生成 Artifact {artifact['id']}", stage="llm")

    def _run_media(self, job_id: str, node_run_id: str, payload: dict[str, Any], capability: str) -> None:
        from app.integrations.media import generate_image as gen_image
        from app.integrations.media import generate_video as gen_video

        with UnitOfWork(self.database) as uow:
            job = uow.jobs.get(job_id)
            provider = self._provider(uow, capability)
            project_id = job["project_id"]
            unit_id = job["unit_id"]
            media_store = self.media_store
        prompt = str(payload.get("prompt") or "")
        parameters = dict(payload.get("parameters") or {})
        data = gen_image(provider, prompt, parameters) if capability == "image" else gen_video(provider, prompt, parameters)
        suffix = ".png" if capability == "image" else ".mp4"
        mime_type = "image/png" if capability == "image" else "video/mp4"
        with UnitOfWork(self.database) as uow:
            uri, sha256 = media_store.write_bytes(
                project_id, data, suffix, unit_id=unit_id
            )
            asset = uow.assets.create(
                {
                    "project_id": project_id,
                    "unit_id": unit_id,
                    "kind": capability,
                    "name": payload.get("name") or f"AI {capability}",
                    "uri": uri,
                    "mime_type": mime_type,
                    "sha256": sha256,
                    "generation": {"provider": provider["id"], "prompt": prompt, "parameters": parameters},
                }
            )
            uow.jobs.update_state(job_id, "running", progress=80.0, result={"asset_id": asset["id"]})
            uow.jobs.add_event(job_id, f"{capability} 素材已生成 {asset['id']}", stage=capability)

    def _run_tts(self, job_id: str, node_run_id: str, payload: dict[str, Any]) -> None:
        from app.integrations.tts.edge import synthesize_edge

        with UnitOfWork(self.database) as uow:
            job = uow.jobs.get(job_id)
            text = str(payload.get("text") or "")
            voice = str(payload.get("voice") or "zh-CN-XiaoxiaoNeural")
            rate = str(payload.get("rate") or "+0%")
            pitch = str(payload.get("pitch") or "+0Hz")
            unit_id = job["unit_id"]
            project_id = job["project_id"]
        uri = synthesize_edge(self.settings, project_id, text, voice, rate, pitch, ".mp3", unit_id)
        with UnitOfWork(self.database) as uow:
            asset = uow.assets.create(
                {
                    "project_id": project_id,
                    "unit_id": unit_id,
                    "kind": "voice",
                    "name": payload.get("name") or "配音",
                    "uri": uri,
                    "mime_type": "audio/mpeg",
                    "sha256": "",
                    "generation": {"provider": "edge-tts", "voice": voice, "rate": rate},
                }
            )
            uow.jobs.update_state(job_id, "running", progress=80.0, result={"asset_id": asset["id"]})
            uow.jobs.add_event(job_id, f"配音已生成 {asset['id']}", stage="tts")

    def _run_voice_synthesis(self, job_id: str, node_run_id: str, payload: dict[str, Any]) -> None:
        from app.application.voice_service import synthesize_lines

        with UnitOfWork(self.database) as uow:
            job = uow.jobs.get(job_id)
            project_id = job["project_id"]
            unit_id = job["unit_id"]
        assets = synthesize_lines(self.settings, self.database, project_id, unit_id, payload.get("lines") or [])
        with UnitOfWork(self.database) as uow:
            uow.jobs.update_state(
                job_id,
                "running",
                progress=90.0,
                result={"asset_ids": [asset["id"] for asset in assets], "count": len(assets)},
            )
            uow.jobs.add_event(job_id, f"已合成 {len(assets)} 条声音", stage="voice")

    def _run_workflow(self, job_id: str, node_run_id: str, payload: dict[str, Any]) -> None:
        workflow_id = payload.get("workflow_id")
        with UnitOfWork(self.database) as uow:
            job = uow.jobs.get(job_id)
            workflow = uow.workflows.get(workflow_id) if workflow_id else None
            if not workflow:
                raise ValueError("workflow_id is required")
            definition = workflow["definition"]
            project_id = job["project_id"]
            unit_id = job["unit_id"]
            context = dict(payload.get("context") or {})
            artifacts = uow.artifacts.list(project_id, unit_id=unit_id)
            for artifact in artifacts:
                if artifact.get("current_version"):
                    context[artifact["kind"]] = artifact["current_version"]["payload"]
        entry_nodes = definition.get("entry_nodes") or list((definition.get("nodes") or {}).keys())
        nodes = definition.get("nodes") or {}
        edges = definition.get("edges") or []
        successors: dict[str, list[str]] = {key: [] for key in nodes}
        for edge in edges:
            successors.setdefault(edge["source"], []).append(edge["target"])
        for node_key in entry_nodes:
            node = nodes[node_key]
            node_context = dict(context)
            for input_name in node.get("inputs", []):
                if input_name in context:
                    node_context[input_name] = context[input_name]
            node_payload = {
                "node_key": node_key,
                "capability": node.get("required_capability", "llm"),
                "prompt": node.get("prompt", ""),
                "schema_id": node.get("schema_id", "freeform"),
                "artifact_kind": node_key,
                "artifact_name": node.get("label") or node_key,
                "context": node_context,
                "parameters": node.get("parameters", {}),
            }
            with UnitOfWork(self.database) as uow:
                sub_job = uow.jobs.create(
                    {
                        "project_id": job["project_id"],
                        "unit_id": job["unit_id"],
                        "job_type": "workflow_node",
                        "payload": node_payload,
                    }
                )
            self.submit(sub_job["id"])
        with UnitOfWork(self.database) as uow:
            uow.jobs.update_state(
                job_id,
                "running",
                progress=90.0,
                result={"dispatched": entry_nodes},
            )

    def _run_render(self, job_id: str, node_run_id: str, payload: dict[str, Any]) -> None:
        from app.application.timeline_render import render_timeline

        with UnitOfWork(self.database) as uow:
            job = uow.jobs.get(job_id)
            timeline = payload.get("timeline") or {}
            project_id = job["project_id"]
            unit_id = job["unit_id"]
        output_uri, duration = render_timeline(self.settings, project_id, timeline)
        with UnitOfWork(self.database) as uow:
            asset = uow.assets.create(
                {
                    "project_id": project_id,
                    "unit_id": unit_id,
                    "kind": "render",
                    "name": payload.get("name") or "成片",
                    "uri": output_uri,
                    "mime_type": "video/mp4",
                    "sha256": "",
                    "metadata": {"duration": duration},
                }
            )
            uow.jobs.update_state(
                job_id,
                "running",
                progress=90.0,
                result={"asset_id": asset["id"], "uri": output_uri, "duration": duration},
            )
            uow.jobs.add_event(job_id, f"成片已渲染 {asset['id']}", stage="render")

    @staticmethod
    def _provider(uow, capability: str) -> dict[str, Any]:
        for provider in uow.providers.list():
            if provider["capability_type"] == capability and provider["enabled"]:
                return uow.providers.get(provider["id"], include_secret=True)
        raise RuntimeError(f"没有启用的 {capability} 渠道")


job_engine: JobEngine | None = None


def get_job_engine(app) -> JobEngine:
    global job_engine
    if job_engine is None:
        job_engine = JobEngine(app.state.database, app.state.settings, app.state.media_store)
    return job_engine
