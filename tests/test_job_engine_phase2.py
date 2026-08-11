import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

SERVER_STATE = {
    "concurrent": 0,
    "max_concurrent": 0,
    "lock": threading.Lock(),
    "llm_delay": 0.0,
    "llm_500_first": 0,
    "image_b64": "",
}


class Phase2Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if self.path == "/chat/completions":
            with SERVER_STATE["lock"]:
                SERVER_STATE["concurrent"] += 1
                SERVER_STATE["max_concurrent"] = max(
                    SERVER_STATE["max_concurrent"], SERVER_STATE["concurrent"]
                )
            try:
                if SERVER_STATE["llm_500_first"] > 0:
                    with SERVER_STATE["lock"]:
                        SERVER_STATE["llm_500_first"] -= 1
                    body = json.dumps({"detail": "boom"}).encode()
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                delay = SERVER_STATE["llm_delay"]
                if delay:
                    time.sleep(delay)
                body = json.dumps(
                    {"choices": [{"message": {"content": json.dumps({"final": "ok"}, ensure_ascii=False)}}]}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            finally:
                with SERVER_STATE["lock"]:
                    SERVER_STATE["concurrent"] -= 1
        elif self.path == "/images/generations":
            body = json.dumps(
                {"data": [{"b64_json": SERVER_STATE["image_b64"]}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)


@pytest.fixture()
def phase2_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Phase2Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    SERVER_STATE.update(
        concurrent=0,
        max_concurrent=0,
        llm_delay=0.0,
        llm_500_first=0,
        image_b64="",
    )
    yield server
    server.shutdown()
    thread.join(timeout=3)


def _add_provider(client, base_url, capability, adapter):
    response = client.post(
        "/api/provider-profiles",
        json={
            "name": f"渠道-{capability}",
            "capability_type": capability,
            "adapter": adapter,
            "base_url": base_url,
            "api_key": "test",
            "enabled": True,
            "models": [
                {"name": "m", "model_id": "m", "capability_type": capability}
            ],
        },
    )
    assert response.status_code == 201


def _wait_job(client, job_id, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed", "canceled"):
            return job
        time.sleep(0.2)
    raise AssertionError(f"job 未结束：{job_id}")
def test_bounded_workers(client, project, phase2_server):
    SERVER_STATE["llm_delay"] = 0.4
    _add_provider(client, f"http://127.0.0.1:{phase2_server.server_port}", "llm", "unknown")
    job_ids = []
    for index in range(6):
        response = client.post(
            f"/api/projects/{project['id']}/generate",
            json={
                "capability": "llm",
                "prompt": "生成一句话",
                "artifact_kind": "generated",
                "artifact_name": f"稿{index}",
            },
        )
        assert response.status_code == 201
        job_ids.append(response.json()["id"])
    for job_id in job_ids:
        job = _wait_job(client, job_id, timeout=40)
        assert job["status"] == "succeeded", job
    assert SERVER_STATE["max_concurrent"] <= 4, SERVER_STATE["max_concurrent"]


def test_job_cancel_stops_quickly(client, project, phase2_server):
    SERVER_STATE["llm_delay"] = 3.0
    _add_provider(client, f"http://127.0.0.1:{phase2_server.server_port}", "llm", "unknown")
    response = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"capability": "llm", "prompt": "慢慢生成"},
    )
    job_id = response.json()["id"]
    time.sleep(0.3)
    cancel = client.post(f"/api/jobs/{job_id}/cancel")
    assert cancel.status_code == 200
    job = _wait_job(client, job_id, timeout=15)
    assert job["status"] == "canceled"
    assert any(event["level"] == "warning" for event in job["events"])


def test_job_retries_then_succeeds(client, project, phase2_server):
    SERVER_STATE["llm_500_first"] = 1
    SERVER_STATE["llm_delay"] = 0.0
    _add_provider(client, f"http://127.0.0.1:{phase2_server.server_port}", "llm", "unknown")
    response = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"capability": "llm", "prompt": "会失败一次"},
    )
    job_id = response.json()["id"]
    job = _wait_job(client, job_id, timeout=25)
    assert job["status"] == "succeeded", job
    assert job["attempt"] >= 2
    assert any("重试" in event["message"] for event in job["events"])


def test_regenerating_edit_plan_appends_version(client, project, phase2_server):
    """重复生成制作方案必须复用同一稿件，不能堆出多份 v1。"""
    _add_provider(
        client,
        f"http://127.0.0.1:{phase2_server.server_port}",
        "llm",
        "unknown",
    )

    def generate():
        response = client.post(
            f"/api/projects/{project['id']}/generate",
            json={
                "capability": "llm",
                "prompt": "生成制作方案",
                "schema_id": "open/edit_plan@1",
                "artifact_kind": "edit_plan",
                "artifact_name": "制作方案",
            },
        )
        assert response.status_code == 201
        job = _wait_job(client, response.json()["id"])
        assert job["status"] == "succeeded", job

    generate()
    generate()

    page = client.get(
        f"/api/projects/{project['id']}/artifacts",
        params={"kind": "edit_plan", "include_payload": True},
    ).json()
    assert len(page["items"]) == 1
    artifact = page["items"][0]
    assert artifact["current_version"]["version"] == 2
    versions = client.get(f"/api/artifacts/{artifact['id']}/versions").json()
    assert [item["version"] for item in versions] == [2, 1]


def test_batch_generation_creates_assets(client, project, phase2_server):
    import struct
    import zlib

    # 1x1 红色 PNG
    def png_bytes():
        raw = b"\x00" + b"\xff\x00\x00\xff" * 1
        def chunk(tag, data):
            c = tag + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b"")
        )

    SERVER_STATE["image_b64"] = base64.b64encode(png_bytes()).decode()
    _add_provider(client, f"http://127.0.0.1:{phase2_server.server_port}", "image", "openai")
    units_response = client.post(
        f"/api/projects/{project['id']}/units",
        json={
            "units": [
                {"title": "镜头A", "unit_type": "shot", "summary": "晨光"},
                {"title": "镜头B", "unit_type": "shot", "summary": "黄昏"},
                {"title": "镜头C", "unit_type": "shot", "summary": "夜景"},
            ]
        },
    )
    assert units_response.status_code == 201
    unit_ids = [unit["id"] for unit in units_response.json()]
    batch = client.post(
        f"/api/projects/{project['id']}/generate/batch",
        json={
            "unit_ids": unit_ids,
            "capability": "image",
            "prompt_template": "绘制 {unit.title}：{unit.summary}，风格 {bible.style.visual_direction}",
            "params": {},
        },
    )
    assert batch.status_code == 201, batch.text
    parent_id = batch.json()["parent_job_id"]
    child_ids = batch.json()["child_job_ids"]
    parent = _wait_job(client, parent_id, timeout=40)
    assert parent["status"] == "succeeded", parent
    for child_id in child_ids:
        child = _wait_job(client, child_id, timeout=40)
        assert child["status"] == "succeeded", child
    assets = client.get(f"/api/projects/{project['id']}/assets").json()["items"]
    image_assets = [asset for asset in assets if asset["kind"] == "image"]
    assert len(image_assets) == 3
    for asset in image_assets:
        assert not asset["uri"].startswith(("/", "data/", "C:", "D:")), asset["uri"]
        assert asset["uri"].startswith(project["id"] + "/"), asset["uri"]
        assert asset["thumb_uri"], asset
        assert asset["metadata"].get("width") == 1


def test_lease_recovery_requeues_stale_jobs(app, client, project, phase2_server):
    """杀服务后：lease 过期的 running 任务被 recover 打回 queued，并重新被 worker 执行成功。"""
    import time

    from sqlalchemy import text

    from app.application.jobs import queue as job_queue
    from app.application.job_engine import get_job_engine
    from app.store import UnitOfWork

    SERVER_STATE["llm_delay"] = 0.0
    _add_provider(client, f"http://127.0.0.1:{phase2_server.server_port}", "llm", "unknown")

    job_id = "stale-" + str(int(time.time() * 1000))
    with UnitOfWork(app.state.database) as uow:
        uow.jobs.create(
            {
                "id": job_id,
                "project_id": project["id"],
                "job_type": "llm",
                "payload": {"capability": "llm", "prompt": "恢复执行"},
            }
        )
    # 模拟上一次进程崩溃：任务停留在 running、worker 失联、lease 过期
    with app.state.database.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE jobs SET status='running', worker_id='dead-worker', "
                "lease_until=:lease WHERE id=:id"
            ),
            {"lease": time.time() - 10, "id": job_id},
        )

    recovered = job_queue.recover(app.state.database)
    assert recovered == 1
    with app.state.database.engine.begin() as conn:
        status = conn.execute(
            text("SELECT status FROM jobs WHERE id=:id"), {"id": job_id}
        ).scalar_one()
    assert status == "queued"

    get_job_engine(app)  # 启动 worker 拾取恢复后的任务
    job = _wait_job(client, job_id, timeout=20)
    assert job["status"] == "succeeded", job
    assert job["attempt"] == 1
    assert job["worker_id"] != "dead-worker"


def test_lease_renewal_protects_long_running_jobs(app, project):
    """长任务必须靠续约保住 lease，否则会被 recover 打回 queued 后重复执行。

    视频生成、渲染这类任务轻易超过 LEASE_SECONDS；没有续约时 reaper 会把它们
    重新入队，另一个 worker 并发跑同一个任务，产出重复素材。
    """
    import time

    from sqlalchemy import text

    from app.application.jobs import queue as job_queue
    from app.store import UnitOfWork

    job_id = "lease-" + str(int(time.time() * 1000))
    with UnitOfWork(app.state.database) as uow:
        uow.jobs.create(
            {
                "id": job_id,
                "project_id": project["id"],
                "job_type": "llm",
                "payload": {"capability": "llm", "prompt": "长任务"},
            }
        )

    def status_of() -> str:
        with app.state.database.engine.begin() as conn:
            return conn.execute(
                text("SELECT status FROM jobs WHERE id=:id"), {"id": job_id}
            ).scalar_one()

    # 用 1 秒的短 lease 认领，模拟"任务耗时远超 lease"
    claimed = job_queue.claim(app.state.database, "worker-under-test", lease_seconds=1)
    assert claimed is not None and claimed["id"] == job_id
    assert status_of() == "running"

    time.sleep(1.2)

    # 续约前：lease 已过期，reaper 会把它打回 queued —— 这正是重复执行的入口
    assert job_queue.renew(app.state.database, [job_id], lease_seconds=60) == 1
    assert job_queue.recover(app.state.database) == 0
    assert status_of() == "running"

    # 续约只作用于 running 的任务，不会把已终结的任务复活
    with app.state.database.engine.begin() as conn:
        conn.execute(
            text("UPDATE jobs SET status='succeeded' WHERE id=:id"), {"id": job_id}
        )
    assert job_queue.renew(app.state.database, [job_id]) == 0
    assert job_queue.renew(app.state.database, []) == 0


def test_engine_tracks_running_jobs_for_heartbeat(app, client, project, phase2_server):
    """引擎必须登记正在执行的任务，心跳线程才有东西可续约。"""
    from app.application.job_engine import get_job_engine

    SERVER_STATE["llm_delay"] = 1.0
    _add_provider(client, f"http://127.0.0.1:{phase2_server.server_port}", "llm", "unknown")
    engine = get_job_engine(app)
    assert engine._heartbeat is not None and engine._heartbeat.is_alive()

    job = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"capability": "llm", "prompt": "慢任务"},
    ).json()

    seen_registered = False
    for _ in range(60):
        if job["id"] in engine._running_jobs:
            seen_registered = True
            break
        time.sleep(0.1)
    assert seen_registered, "运行中的任务未登记，心跳无法续约"

    _wait_job(client, job["id"], timeout=20)
    SERVER_STATE["llm_delay"] = 0.0
    assert job["id"] not in engine._running_jobs
