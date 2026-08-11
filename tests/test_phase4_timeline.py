"""Phase 4：时间线编译、版本 diff/回滚、版本状态机。"""

from app.store.repositories import ConflictError
from app.store import UnitOfWork


def _add_asset(client, project_id, kind, unit_id, metadata=None, uri=None):
    response = client.post(
        f"/api/projects/{project_id}/assets",
        json={
            "kind": kind,
            "name": f"{kind}-{uri or 'x'}",
            "uri": uri or f"{project_id}/{kind}.png",
            "mime_type": "video/mp4" if kind == "video" else "audio/mpeg",
            "unit_id": unit_id,
            "metadata": metadata or {},
        },
    )
    assert response.status_code == 201
    return response.json()


def test_timeline_compile_uses_asset_ids_and_metadata(client, project):
    unit = client.post(
        f"/api/projects/{project['id']}/units",
        json={"units": [{"title": "镜头", "unit_type": "shot"}]},
    ).json()[0]
    video = _add_asset(client, project["id"], "video", unit["id"], {"duration": 2.5}, f"{project['id']}/v.mp4")
    voice = _add_asset(client, project["id"], "voice", unit["id"], {"duration": 1.2}, f"{project['id']}/v.mp3")
    # 无 edit_plan：回落按顺序排布
    compiled = client.post(
        f"/api/projects/{project['id']}/timeline/compile",
        json={"unit_id": None, "parameters": {"default_clip_seconds": 3}},
    ).json()["timeline"]
    by_kind = {track["kind"]: track["clips"] for track in compiled["tracks"]}
    video_clip = by_kind["video"][0]
    assert video_clip["asset_id"] == video["id"], "asset_id 必须是素材 id 而不是路径"
    assert video_clip["range"]["duration"] == 2.5  # ffprobe 探测值优先于默认值
    assert video_clip["metadata"]["unit_id"] == unit["id"]
    voice_clip = by_kind["voice"][0]
    assert voice_clip["asset_id"] == voice["id"]
    assert voice_clip["range"]["start"] == video_clip["range"]["start"], "配音应对齐到同单元视频起点"
    assert voice_clip["range"]["duration"] == 1.2


def test_timeline_recompile_appends_version_to_same_artifact(client, project):
    """同一作用域重复编译只能产生一份 timeline artifact，并顺序追加版本。"""
    first = client.post(
        f"/api/projects/{project['id']}/timeline/compile",
        json={"unit_id": None},
    )
    assert first.status_code == 200
    first_artifact = first.json()["artifact"]
    assert first_artifact["current_version"]["version"] == 1

    second = client.post(
        f"/api/projects/{project['id']}/timeline/compile",
        json={"unit_id": None},
    )
    assert second.status_code == 200
    second_artifact = second.json()["artifact"]
    assert second_artifact["id"] == first_artifact["id"]
    assert second_artifact["current_version"]["version"] == 2

    page = client.get(
        f"/api/projects/{project['id']}/artifacts",
        params={"kind": "timeline", "include_payload": True},
    ).json()
    assert [item["id"] for item in page["items"]] == [first_artifact["id"]]
    versions = client.get(f"/api/artifacts/{first_artifact['id']}/versions").json()
    assert [item["version"] for item in versions] == [2, 1]


def test_edit_plan_prefers_approved_status(client, project):
    asset = _add_asset(client, project["id"], "video", None, {"duration": 1.0}, f"{project['id']}/plan.mp4")
    client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={
            "kind": "edit_plan",
            "name": "草稿方案",
            "payload": {"decisions": [{"asset_id": asset["id"], "reason": "draft", "duration": 1}]},
        },
    ).json()
    approved = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={
            "kind": "edit_plan",
            "name": "已确认方案",
            "payload": {"decisions": [{"asset_id": asset["id"], "reason": "approved", "duration": 1}]},
        },
    ).json()
    response = client.post(
        f"/api/artifact-versions/{approved['current_version']['id']}/approve"
    )
    assert response.status_code == 200
    compiled = client.post(
        f"/api/projects/{project['id']}/timeline/compile",
        json={"unit_id": None},
    ).json()["timeline"]
    video_clips = next(track["clips"] for track in compiled["tracks"] if track["kind"] == "video")
    assert video_clips[0]["metadata"]["reason"] == "approved"


def test_version_diff_and_restore(client, project):
    artifact = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={"kind": "script", "name": "剧本", "payload": {"a": 1, "b": {"x": 1}}},
    ).json()
    v2 = client.post(
        f"/api/artifacts/{artifact['id']}/versions",
        json={"payload": {"a": 2, "b": {"x": 1, "y": 2}}, "note": "第二版"},
    ).json()
    v1 = artifact["current_version"]
    diff = client.get(f"/api/artifact-versions/{v1['id']}/diff/{v2['id']}").json()
    paths = {item["path"] for item in diff["field_diffs"]}
    assert "/a" in paths
    assert "/b/y" in paths

    restored = client.post(f"/api/artifacts/{artifact['id']}/restore/{v1['id']}").json()
    assert restored["version"] == 3
    assert restored["payload"] == {"a": 1, "b": {"x": 1}}
    versions = client.get(f"/api/artifacts/{artifact['id']}/versions").json()
    assert len(versions) == 3


def test_version_status_machine_forward_only(client, project):
    artifact = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={"kind": "script", "name": "剧本", "payload": {"body": "x"}},
    ).json()
    version = artifact["current_version"]

    approved = client.post(f"/api/artifact-versions/{version['id']}/approve")
    assert approved.status_code == 200
    locked = client.post(f"/api/artifact-versions/{version['id']}/lock")
    assert locked.status_code == 200
    # locked 是终态：不允许退回 draft
    with UnitOfWork(client.app.state.database) as uow:
        try:
            uow.artifacts.set_status(version["id"], "draft")
            raise AssertionError("locked -> draft 应当被拒绝")
        except ConflictError:
            pass

    # draft 可以直接锁（合法前进）
    artifact2 = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={"kind": "script", "name": "另一份", "payload": {"body": "y"}},
    ).json()
    lock = client.post(f"/api/artifact-versions/{artifact2['current_version']['id']}/lock")
    assert lock.status_code == 200
