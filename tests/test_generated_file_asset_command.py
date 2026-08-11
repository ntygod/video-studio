from app.application.commands import (
    CommandBus, CommandContext, PersistGeneratedFileAssetCommand,
    job_asset_persistence_attempt,
)
from app.store import UnitOfWork


def test_generated_file_asset_is_adopted_and_replayed(app, project):
    source_uri, _ = app.state.media_store.write_bytes(
        project["id"], b"rendered bytes", ".mp4"
    )
    job_id = "render-job"
    key = f"job:{job_id}:asset:1"
    first = CommandBus(app.state.database).execute(
        PersistGeneratedFileAssetCommand(
            project_id=project["id"], source_uri=source_uri,
            media_store=app.state.media_store, kind="render",
            name="预览", mime_type="video/mp4",
            metadata={"duration": 1.5},
        ),
        CommandContext(
            actor_type="job", actor_id=job_id,
            idempotency_key=key,
        ),
    ).result
    assert first["uri"] != source_uri
    assert not app.state.media_store.path_for(source_uri).exists()
    assert app.state.media_store.path_for(first["uri"]).exists()

    recovered, recovered_key = job_asset_persistence_attempt(
        app.state.database, job_id
    )
    assert recovered_key == key
    assert recovered["id"] == first["id"]
    with UnitOfWork(app.state.database) as uow:
        operation = uow.operations.find_by_idempotency_key(key)
    assert operation["operation_type"] == "asset.generated-file.persist"


def test_failed_asset_attempt_receives_new_key(app, project):
    job_id = "failed-media-job"
    with UnitOfWork(app.state.database) as uow:
        operation = uow.operations.create({
            "project_id": project["id"],
            "operation_type": "asset.generated.persist",
            "actor_type": "job", "actor_id": job_id,
            "target_type": "project", "target_id": project["id"],
            "idempotency_key": f"job:{job_id}:asset:1",
            "arguments": {}, "preconditions": [],
        })
        uow.operations.fail(operation["id"], "provider output invalid")
    existing, key = job_asset_persistence_attempt(app.state.database, job_id)
    assert existing is None
    assert key == f"job:{job_id}:asset:2"
