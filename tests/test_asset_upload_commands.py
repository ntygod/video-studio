import struct
import zlib

from app.application.commands.recovery import (
    recover_interrupted_operations,
)
from app.store import UnitOfWork


def _png_bytes(width: int = 1, height: int = 1) -> bytes:
    raw = b"".join(
        b"\x00" + b"\xff\x00\x00\xff" * width
        for _ in range(height)
    )

    def chunk(tag: bytes, data: bytes) -> bytes:
        value = tag + data
        return (
            struct.pack(">I", len(data))
            + value
            + struct.pack(">I", zlib.crc32(value) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(
        ">IIBBBBB",
        width,
        height,
        8,
        6,
        0,
        0,
        0,
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_asset_upload_is_idempotent_and_operation_named(
    app,
    client,
    project,
):
    data = _png_bytes(2, 3)
    headers = {"Idempotency-Key": "upload-reference-once"}

    first = client.post(
        f"/api/projects/{project['id']}/assets/upload",
        headers=headers,
        files={"file": ("reference.png", data, "image/png")},
        data={"kind": "reference", "name": "参考图"},
    )
    second = client.post(
        f"/api/projects/{project['id']}/assets/upload",
        headers=headers,
        files={"file": ("reference.png", data, "image/png")},
        data={"kind": "reference", "name": "参考图"},
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()

    asset = first.json()
    assert asset["metadata"]["width"] == 2
    assert asset["metadata"]["height"] == 3
    assert app.state.media_store.path_for(asset["uri"]).exists()

    with UnitOfWork(app.state.database) as uow:
        operation = uow.operations.find_by_idempotency_key(
            "upload-reference-once"
        )
        assets = uow.assets.list(project["id"])
    assert operation["operation_type"] == "asset.upload"
    assert operation["status"] == "succeeded"
    assert operation["arguments"]["content_sha256"]
    assert "content" not in operation["arguments"]
    assert operation["id"] in asset["uri"]
    assert [item["id"] for item in assets].count(asset["id"]) == 1


def test_interrupted_upload_file_is_cleaned_before_failure(
    app,
    project,
):
    with UnitOfWork(app.state.database) as uow:
        operation = uow.operations.create(
            {
                "project_id": project["id"],
                "operation_type": "asset.upload",
                "target_type": "project",
                "target_id": project["id"],
                "arguments": {},
                "preconditions": [],
            }
        )

    uri, _ = app.state.media_store.write_operation_bytes(
        project["id"],
        _png_bytes(),
        ".png",
        operation["id"],
    )
    assert app.state.media_store.path_for(uri).exists()

    recovered = recover_interrupted_operations(
        app.state.database,
        media_store=app.state.media_store,
    )
    assert recovered == 1
    assert not app.state.media_store.path_for(uri).exists()
    with UnitOfWork(app.state.database) as uow:
        failed = uow.operations.get(operation["id"])
    assert failed["status"] == "failed"
    assert "interrupted" in failed["error"]


def test_empty_upload_is_rejected_without_media_file(
    app,
    client,
    project,
):
    response = client.post(
        f"/api/projects/{project['id']}/assets/upload",
        headers={"Idempotency-Key": "empty-upload"},
        files={"file": ("empty.bin", b"", "application/octet-stream")},
    )
    assert response.status_code == 422
    with UnitOfWork(app.state.database) as uow:
        operation = uow.operations.find_by_idempotency_key(
            "empty-upload"
        )
    assert operation["status"] == "failed"
    assert app.state.media_store.cleanup_operation_files(
        operation["id"]
    ) == []
