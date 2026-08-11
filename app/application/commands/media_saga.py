"""Cross-resource helpers shared by media-backed commands."""

from __future__ import annotations

import os
from typing import Any


def quarantine_project_directory(
    media_store: Any,
    project_id: str,
    operation_id: str,
) -> list[str]:
    """Move a complete project media tree into an Operation quarantine.

    The move is a same-filesystem rename when the media root is local. The
    returned manifest is audit-only; rollback uses MediaStore's generic
    restore routine, which rebuilds the original relative paths.
    """

    root = media_store.root.resolve()
    source = (root / project_id).resolve()
    if source.parent != root:
        raise ValueError("invalid project media directory")
    if not source.exists():
        return []

    trash = media_store._trash_dir(operation_id)  # central validation
    target = (trash / project_id).resolve()
    if trash.resolve() not in target.parents:
        raise ValueError("invalid project quarantine path")
    if target.exists():
        raise RuntimeError(
            f"project quarantine already exists: {project_id}"
        )

    manifest = [
        path.relative_to(root).as_posix()
        for path in source.rglob("*")
        if path.is_file()
    ]
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, target)
    return sorted(manifest)


__all__ = ["quarantine_project_directory"]
