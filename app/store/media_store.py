"""媒体存储：相对 URI、媒体探测、缩略图与音频波形。"""

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path


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
    def _safe_suffix(suffix: str) -> str:
        raw = str(suffix or "").lower().lstrip(".")
        cleaned = "".join(
            character
            for character in raw
            if character.isalnum()
        )[:16]
        return f".{cleaned or 'bin'}"

    def write_bytes(
        self,
        project_id: str,
        data: bytes,
        suffix: str,
        unit_id: str | None = None,
    ) -> tuple[str, str]:
        """写入文件并返回 (相对 uri, sha256)。"""
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
        """以 Operation ID 写入确定性文件，支持请求幂等与崩溃清理。"""

        if not operation_id or not all(
            character.isalnum() or character in "-_"
            for character in operation_id
        ):
            raise ValueError("invalid operation id")
        folder = self.project_dir(project_id)
        if unit_id:
            folder = folder / unit_id
            folder.mkdir(parents=True, exist_ok=True)
        suffix = self._safe_suffix(suffix)
        name = f"{operation_id}{suffix}"
        target = folder / name
        digest = hashlib.sha256(data).hexdigest()
        if target.exists():
            current = hashlib.sha256(target.read_bytes()).hexdigest()
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

    def cleanup_operation_files(self, operation_id: str) -> list[str]:
        """清理中断上传留下的确定性文件及其派生预览。"""

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
        # 只移除已空的项目/单元目录，不影响其他媒体。
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
        """从常见图片文件头读取尺寸，避免小图片依赖 ffprobe。"""

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
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
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
        """探测 width/height/duration/codec；图片优先走文件头，其余使用 ffprobe。"""
        path = self.path_for(relative_uri)
        image_meta = self._probe_image_header(path)
        if image_meta is not None:
            return image_meta

        command = [
            self.ffprobe_path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
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
        """图片缩放 640 长边；视频抽 1s 帧；音频算 200 点波形峰值存 JSON。"""
        source = self.path_for(relative_uri)
        if mime_type.startswith("image/"):
            thumb_uri = relative_uri + ".thumb.png"
            target = self.path_for(thumb_uri)
            self._run_ffmpeg(
                [
                    "-y",
                    "-i",
                    str(source),
                    "-vf",
                    "scale='min(640,iw)':-1",
                    "-frames:v",
                    "1",
                    str(target),
                ]
            )
            return thumb_uri
        if mime_type.startswith("video/"):
            thumb_uri = relative_uri + ".thumb.jpg"
            target = self.path_for(thumb_uri)
            self._run_ffmpeg(
                [
                    "-y",
                    "-ss",
                    "1",
                    "-i",
                    str(source),
                    "-vf",
                    "scale='min(640,iw)':-2",
                    "-frames:v",
                    "1",
                    "-q:v",
                    "4",
                    str(target),
                ]
            )
            return thumb_uri
        if mime_type.startswith("audio/"):
            wave_uri = relative_uri + ".wave.json"
            target = self.path_for(wave_uri)
            peaks = self._audio_waveform(source)
            target.write_text(json.dumps(peaks), encoding="utf-8")
            return wave_uri
        raise ValueError(f"unsupported thumb mime: {mime_type}")

    def _run_ffmpeg(self, args: list[str]) -> None:
        result = subprocess.run(
            [self.ffmpeg_path, *args], capture_output=True, text=True, timeout=600
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")

    def _audio_waveform(self, source: Path, bins: int = 200) -> list[float]:
        """ffmpeg 解码为单声道 f32le，按 200 个 bin 取峰值，归一化到 0-1。"""
        result = subprocess.run(
            [
                self.ffmpeg_path,
                "-v",
                "error",
                "-i",
                str(source),
                "-ac",
                "1",
                "-f",
                "f32le",
                "-",
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
            extra = Path(str(path) + suffix)
            extra.unlink(missing_ok=True)
