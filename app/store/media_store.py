import hashlib
import os
import uuid
from pathlib import Path


class MediaStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def project_dir(self, project_id: str) -> Path:
        path = self.root / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_bytes(
        self,
        project_id: str,
        data: bytes,
        suffix: str,
        unit_id: str | None = None,
    ) -> tuple[str, str]:
        folder = self.project_dir(project_id)
        if unit_id:
            folder = folder / unit_id
            folder.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}{suffix}"
        target = folder / name
        temp = folder / f".{name}.tmp"
        temp.write_bytes(data)
        os.replace(temp, target)
        return target.as_posix(), hashlib.sha256(data).hexdigest()

    def delete_project(self, project_id: str) -> None:
        import shutil

        shutil.rmtree(self.root / project_id, ignore_errors=True)

    def delete_asset(self, uri: str) -> None:
        if not uri:
            return
        path = Path(uri)
        if path.is_absolute() and self.root in path.parents:
            path.unlink(missing_ok=True)
        elif not path.is_absolute():
            relative = self.root / path
            relative.unlink(missing_ok=True)
