from app.application.commands import (
    CommandBus,
    CommandContext,
    PersistGeneratedFileAssetCommand,
    job_asset_persistence_attempt,
)


def _persist_slot(app, project_id: str, job_id: str, slot: str, data: bytes):
    source_uri, _ = app.state.media_store.write_bytes(
        project_id, data, ".mp3"
    )
    _, key = job_asset_persistence_attempt(
        app.state.database, job_id, slot=slot
    )
    return CommandBus(app.state.database).execute(
        PersistGeneratedFileAssetCommand(
            project_id=project_id,
            source_uri=source_uri,
            media_store=app.state.media_store,
            kind="voice",
            name=slot,
            mime_type="audio/mpeg",
            generation={"slot": slot},
        ),
        CommandContext(
            actor_type="job",
            actor_id=job_id,
            idempotency_key=key,
        ),
    ).result


def test_voice_line_slots_recover_independently(app, project):
    job_id = "voice-batch-job"
    first = _persist_slot(
        app, project["id"], job_id, "voice-line-0", b"line zero"
    )
    second = _persist_slot(
        app, project["id"], job_id, "voice-line-1", b"line one"
    )

    recovered_first, first_key = job_asset_persistence_attempt(
        app.state.database, job_id, slot="voice-line-0"
    )
    recovered_second, second_key = job_asset_persistence_attempt(
        app.state.database, job_id, slot="voice-line-1"
    )
    missing, third_key = job_asset_persistence_attempt(
        app.state.database, job_id, slot="voice-line-2"
    )
    assert recovered_first["id"] == first["id"]
    assert recovered_second["id"] == second["id"]
    assert first_key.endswith(":voice-line-0:1")
    assert second_key.endswith(":voice-line-1:1")
    assert missing is None
    assert third_key.endswith(":voice-line-2:1")


def test_voice_synthesis_job_creation_is_idempotent(client, project):
    headers = {"Idempotency-Key": "voice-job-once"}
    body = {
        "lines": [
            {"speaker": "旁白", "text": "第一句"},
            {"speaker": "角色", "text": "第二句"},
        ]
    }
    first = client.post(
        f"/api/projects/{project['id']}/voice/synthesize",
        json=body,
        headers=headers,
    )
    second = client.post(
        f"/api/projects/{project['id']}/voice/synthesize",
        json=body,
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
