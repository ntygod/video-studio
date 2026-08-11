"""媒体存储：相对 URI、ffprobe 探测、缩略图与音频波形。"""

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

    def write_bytes(
        self,
        project_id: str,
        data: bytes,
        suffix: str,
        unit_id: str | None = None,
    ) -> tuple[str, str]:
        """写入文件并返回 (相对 uri, sha256)。uri 形如 "<project_id>/[<unit_id>/]<uuid><suffix>"。"""
        folder = self.project_dir(project_id)
        if unit_id:
            folder = folder / unit_id
            folder.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}{suffix}"
        target = folder / name
        temp = folder / f".{name}.tmp"
        temp.write_bytes(data)
        os.replace(temp, target)
        relative = f"{project_id}/{unit_id}/" if unit_id else f"{project_id}/"
        return relative + name, hashlib.sha256(data).hexdigest()

    def probe(self, relative_uri: str) -> dict:
        """ffprobe 探测 width/height/duration/codec。"""
        path = self.path_for(relative_uri)
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
                    "scale='min(640,iw)':-2",
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
