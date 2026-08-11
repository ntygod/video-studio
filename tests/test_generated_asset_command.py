import struct
import zlib

from app.application.commands import (
    CommandBus,
    CommandContext,
    PersistGeneratedAssetCommand,
)
from app.store import UnitOfWork


def _png_bytes() -> bytes:
    raw = b"\x00\xff\x00\x00\xff"

    def chunk(tag: bytes, data: bytes) -> bytes:
        value = tag + data
        return (
            struct.pack(">I", len(data))
            + value
            + struct.pack(">I", zlib.crc32(value) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_generated_asset_persistence_is_job_idempotent(
    app,
    project,
):
    context = CommandContext(
        actor_type="job",
        actor_id="job-under-test",
        idempotency_key="job:job-under-test:asset",
    )

    def command():
        return PersistGeneratedAssetCommand(
            project_id=project["id"],
            data=_png_bytes(),
            filename="generated.png",
            media_store=app.state.media_store,
            kind="image",
            name="生成图",
            mime_type="image/png",
            generation={
                "provider": "fake",
                "task_id": "provider-task",
            },
        )

    first = CommandBus(app.state.database).execute(
        command(),
        context,
    )
    second = CommandBus(app.state.database).execute(
        command(),
        context,
    )
    assert second.replayed is True
    assert second.result == first.result
    assert first.result["metadata"]["width"] == 1
    assert app.state.media_store.path_for(
        first.result["uri"]
    ).exists()

    with UnitOfWork(app.state.database) as uow:
        assets = uow.assets.list(project["id"])
        operation = uow.operations.find_by_idempotency_key(
            "job:job-under-test:asset"
        )
    assert [asset["id"] for asset in assets].count(
        first.result["id"]
    ) == 1
    assert operation["operation_type"] == "asset.generated.persist"
    assert operation["actor_type"] == "job"
