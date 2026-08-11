"""媒体存储：相对 URI、媒体探测、缩略图与可恢复隔离。"""

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Iterable


class MediaStore:
    def __init__(self, root: Path, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe"):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path

    def project_dir(self, project_id: str) -> Path:
        path = self.root / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def path_for(self, relative_uri: str) -> Path:
        """把相对 uri（"<project_id>/<unit_id>/<file>"）解析成受保护的绝对路径。"""
        if relative_uri.startswith("/media/"):
            relative_uri = relative_uri[len("/media/") :]
        path = (self.root / relative_uri).resolve()
        root = self.root.resolve()
        if path != root and root not in path.parents:
            raise ValueError("invalid media path")
        return path

    @staticmethod
    def _safe_operation_id(operation_id: str) -> str:
        if not operation_id or not all(
            character.isalnum() or character in "-_"
            for character in operation_id
        ):
            raise ValueError("invalid operation id")
        return operation_id

    @staticmethod
    def _safe_suffix(suffix: str) -> str:
        raw = str(suffix or "").lower().lstrip(".")
        cleaned = "".join(
            character
            for character in raw
            if character.isalnum()
        )[:16]
        return f".{cleaned or 'bin'}"

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

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
        suffix = self._safe_suffix(suffix)
        name = f"{uuid.uuid4().hex}{suffix}"
        target = folder / name
        temp = folder / f".{name}.tmp"
        temp.write_bytes(data)
        os.replace(temp, target)
        relative = f"{project_id}/{unit_id}/" if unit_id else f"{project_id}/"
        return relative + name, hashlib.sha256(data).hexdigest()

    def write_operation_bytes(
        self,
        project_id: str,
        data: bytes,
        suffix: str,
        operation_id: str,
        unit_id: str | None = None,
    ) -> tuple[str, str]:
        operation_id = self._safe_operation_id(operation_id)
        folder = self.project_dir(project_id)
        if unit_id:
            folder = folder / unit_id
            folder.mkdir(parents=True, exist_ok=True)
        suffix = self._safe_suffix(suffix)
        name = f"{operation_id}{suffix}"
        target = folder / name
        digest = hashlib.sha256(data).hexdigest()
        if target.exists():
            current = self._sha256_file(target)
            if current != digest:
                raise RuntimeError(
                    "operation media path already contains different bytes"
                )
        else:
            temp = folder / f".{name}.{uuid.uuid4().hex}.tmp"
            try:
                temp.write_bytes(data)
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
        relative = f"{project_id}/{unit_id}/" if unit_id else f"{project_id}/"
        return relative + name, digest

    def adopt_operation_file(
        self,
        project_id: str,
        source_uri: str,
        operation_id: str,
        unit_id: str | None = None,
    ) -> tuple[str, str]:
        """Move a newly generated file to an Operation-stable media URI."""

        operation_id = self._safe_operation_id(operation_id)
        source = self.path_for(source_uri)
        if not source.is_file():
            raise FileNotFoundError(source_uri)
        suffix = self._safe_suffix(source.suffix)
        folder = self.project_dir(project_id)
        if unit_id:
            folder = folder / unit_id
            folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{operation_id}{suffix}"
        source_hash = self._sha256_file(source)
        if source.resolve() != target.resolve():
            if target.exists():
                if self._sha256_file(target) != source_hash:
                    raise RuntimeError(
                        "operation target contains different generated media"
                    )
                source.unlink()
            else:
                os.replace(source, target)
        relative = f"{project_id}/{unit_id}/" if unit_id else f"{project_id}/"
        return relative + target.name, source_hash

    def _trash_dir(self, operation_id: str) -> Path:
        operation_id = self._safe_operation_id(operation_id)
        path = self.root / ".trash" / operation_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _normalize_uri(relative_uri: str) -> str:
        value = str(relative_uri or "").strip()
        if value.startswith("/media/"):
            value = value[len("/media/") :]
        return value.lstrip("/")

    def quarantine_asset(
        self,
        relative_uris: Iterable[str],
        operation_id: str,
    ) -> list[str]:
        operation_id = self._safe_operation_id(operation_id)
        candidates: set[str] = set()
        for raw_uri in relative_uris:
            uri = self._normalize_uri(raw_uri)
            if not uri:
                continue
            candidates.add(uri)
            for suffix in (".thumb.png", ".thumb.jpg", ".wave.json"):
                candidates.add(uri + suffix)

        trash = self._trash_dir(operation_id)
        moved: list[str] = []
        try:
            for uri in sorted(candidates):
                source = self.path_for(uri)
                if not source.is_file():
                    continue
                target = (trash / uri).resolve()
                if trash.resolve() not in target.parents:
                    raise ValueError("invalid quarantine path")
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise RuntimeError(
                        f"quarantine target already exists: {uri}"
                    )
                os.replace(source, target)
                moved.append(uri)
        except Exception:
            self.restore_operation_quarantine(operation_id)
            raise
        return moved

    def restore_operation_quarantine(
        self,
        operation_id: str,
    ) -> list[str]:
        operation_id = self._safe_operation_id(operation_id)
        trash = self.root / ".trash" / operation_id
        if not trash.exists():
            return []
        restored: list[str] = []
        files = sorted(
            [path for path in trash.rglob("*") if path.is_file()],
            key=lambda path: len(path.parts),
        )
        for source in files:
            relative = source.relative_to(trash)
            target = self.path_for(relative.as_posix())
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                source_hash = self._sha256_file(source)
                target_hash = self._sha256_file(target)
                if source_hash != target_hash:
                    raise RuntimeError(
                        f"cannot restore over different media: {relative}"
                    )
                source.unlink()
            else:
                os.replace(source, target)
            restored.append(relative.as_posix())
        directories = sorted(
            [path for path in trash.rglob("*") if path.is_dir()],
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in directories:
            try:
                directory.rmdir()
            except OSError:
                pass
        try:
            trash.rmdir()
        except OSError:
            pass
        return restored

    def cleanup_operation_files(self, operation_id: str) -> list[str]:
        operation_id = self._safe_operation_id(operation_id)
        removed: list[str] = []
        root = self.root.resolve()
        for path in list(root.rglob(f"*{operation_id}*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if relative.parts and relative.parts[0] == ".trash":
                continue
            path.unlink(missing_ok=True)
            removed.append(relative.as_posix())
        directories = sorted(
            [item for item in root.rglob("*") if item.is_dir()],
            key=lambda item: len(item.parts),
            reverse=True,
        )
        for directory in directories:
            if directory == root or directory.name == ".trash":
                continue
            try:
                directory.rmdir()
            except OSError:
                pass
        return removed

    @staticmethod
    def _probe_image_header(path: Path) -> dict | None:
        with path.open("rb") as stream:
            header = stream.read(32)
            if (
                len(header) >= 24
                and header[:8] == b"\x89PNG\r\n\x1a\n"
                and header[12:16] == b"IHDR"
            ):
                return {
                    "width": int.from_bytes(header[16:20], "big"),
                    "height": int.from_bytes(header[20:24], "big"),
                    "codec": "png",
                }
            if len(header) >= 10 and header[:6] in (b"GIF87a", b"GIF89a"):
                return {
                    "width": int.from_bytes(header[6:8], "little"),
                    "height": int.from_bytes(header[8:10], "little"),
                    "codec": "gif",
                }
            if header[:2] != b"\xff\xd8":
                return None
            stream.seek(2)
            sof_markers = {
                0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
            }
            while True:
                prefix = stream.read(1)
                if not prefix:
                    return None
                if prefix != b"\xff":
                    continue
                marker_bytes = stream.read(1)
                while marker_bytes == b"\xff":
                    marker_bytes = stream.read(1)
                if not marker_bytes:
                    return None
                marker = marker_bytes[0]
                if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                    continue
                length_bytes = stream.read(2)
                if len(length_bytes) != 2:
                    return None
                segment_length = int.from_bytes(length_bytes, "big")
                if segment_length < 2:
                    return None
                if marker in sof_markers:
                    payload = stream.read(5)
                    if len(payload) != 5:
                        return None
                    return {
                        "width": int.from_bytes(payload[3:5], "big"),
                        "height": int.from_bytes(payload[1:3], "big"),
                        "codec": "jpeg",
                    }
                stream.seek(segment_length - 2, 1)

    def probe(self, relative_uri: str) -> dict:
        path = self.path_for(relative_uri)
        image_meta = self._probe_image_header(path)
        if image_meta is not None:
            return image_meta
        command = [
            self.ffprobe_path, "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {result.stderr[-500:]}")
        data = json.loads(result.stdout or "{}")
        streams = data.get("streams") or []
        video = next((item for item in streams if item.get("codec_type") == "video"), None)
        audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
        meta: dict = {}
        try:
            meta["duration"] = float((data.get("format") or {}).get("duration") or 0.0)
        except (TypeError, ValueError):
            meta["duration"] = 0.0
        if video:
            try:
                meta["width"] = int(video.get("width") or 0)
                meta["height"] = int(video.get("height") or 0)
            except (TypeError, ValueError):
                pass
            meta["codec"] = video.get("codec_name") or ""
            if not meta.get("duration") and video.get("duration"):
                try:
                    meta["duration"] = float(video["duration"])
                except (TypeError, ValueError):
                    pass
        if audio and not meta.get("codec"):
            meta["codec"] = audio.get("codec_name") or ""
        return meta

    def make_thumb(self, relative_uri: str, mime_type: str) -> str:
        source = self.path_for(relative_uri)
        if mime_type.startswith("image/"):
            thumb_uri = relative_uri + ".thumb.png"
            target = self.path_for(thumb_uri)
            self._run_ffmpeg([
                "-y", "-i", str(source), "-vf",
                "scale='min(640,iw)':-1", "-frames:v", "1", str(target),
            ])
            return thumb_uri
        if mime_type.startswith("video/"):
            thumb_uri = relative_uri + ".thumb.jpg"
            target = self.path_for(thumb_uri)
            self._run_ffmpeg([
                "-y", "-ss", "1", "-i", str(source), "-vf",
                "scale='min(640,iw)':-2", "-frames:v", "1",
                "-q:v", "4", str(target),
            ])
            return thumb_uri
        if mime_type.startswith("audio/"):
            wave_uri = relative_uri + ".wave.json"
            target = self.path_for(wave_uri)
            target.write_text(
                json.dumps(self._audio_waveform(source)),
                encoding="utf-8",
            )
            return wave_uri
        raise ValueError(f"unsupported thumb mime: {mime_type}")

    def _run_ffmpeg(self, args: list[str]) -> None:
        result = subprocess.run(
            [self.ffmpeg_path, *args],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")

    def _audio_waveform(self, source: Path, bins: int = 200) -> list[float]:
        result = subprocess.run(
            [
                self.ffmpeg_path, "-v", "error", "-i", str(source),
                "-ac", "1", "-f", "f32le", "-",
            ],
            capture_output=True,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg decode failed: {result.stderr[-500:]}")
        raw = result.stdout[: 64 * 1024 * 1024]
        import struct
        count = len(raw) // 4
        if count < bins:
            return [0.0] * bins
        samples = struct.unpack(f"<{count}f", raw[: count * 4])
        per = max(1, count // bins)
        peaks: list[float] = []
        for index in range(bins):
            start = index * per
            end = min(start + per, count)
            window = samples[start:end]
            peaks.append(round(min(1.0, max((abs(sample) for sample in window), default=0.0) * 4.0), 3))
        return peaks

    def delete_project(self, project_id: str) -> None:
        import shutil
        shutil.rmtree(self.root / project_id, ignore_errors=True)

    def delete_asset(self, uri: str) -> None:
        if not uri:
            return
        try:
            path = self.path_for(uri)
        except ValueError:
            return
        path.unlink(missing_ok=True)
        for suffix in (".thumb.png", ".thumb.jpg", ".wave.json"):
            Path(str(path) + suffix).unlink(missing_ok=True)
