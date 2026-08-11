from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from typing import Any


def _resolve(settings, uri: str) -> str:
    if uri.startswith("/media/"):
        uri = uri[len("/media/"):]
    path = Path(uri)
    if path.is_absolute():
        return str(path)
    return str((settings.media_dir / uri).resolve())


def render_timeline(
    settings,
    project_id: str,
    timeline: dict[str, Any],
    progress=None,
    should_cancel=None,
    asset_resolver=None,
):
    """渲染时间线。

    progress: Callable[[float], None] | None，ffmpeg -progress pipe:1 换算成 0-1。
    should_cancel: Callable[[], bool] | None，协作式取消（终止 ffmpeg 进程）。
    asset_resolver: Callable[[str], str] | None，把 clip.asset_id 解析成媒体绝对路径
        （T4.1：asset_id 现在是真实素材 id，需查库后再取 uri）。
    """
    width = int(timeline.get("width", 1080))
    height = int(timeline.get("height", 1920))
    fps = int(timeline.get("fps", 30))
    tracks = timeline.get("tracks") or []
    work_dir = settings.work_dir / project_id
    work_dir.mkdir(parents=True, exist_ok=True)

    video_inputs: list[list[str]] = []
    audio_inputs: list[list[str]] = []
    filters: list[str] = []
    video_labels: list[str] = []
    audio_labels: list[str] = []
    v_index = 0
    a_index = 0

    for track in tracks:
        kind = track.get("kind")
        for clip in track.get("clips") or []:
            asset_id = clip.get("asset_id")
            if not asset_id:
                continue
            path = asset_resolver(asset_id) if asset_resolver else _resolve(settings, asset_id)
            if not path:
                continue
            start = float(clip.get("range", {}).get("start", 0.0))
            duration = float(clip.get("range", {}).get("duration", 1.0))
            if kind in ("video", "image"):
                video_inputs.append(["-i", path])
                label = f"v{v_index}"
                v_index += 1
                if kind == "image":
                    filters.append(
                        f"[{label}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,loop=loop={max(1, int(fps * duration))}:size=1:start=0,"
                        f"trim=duration={duration:.3f},setpts=PTS-STARTPTS[v{v_index - 1}c]"
                    )
                    video_labels.append(f"[v{v_index - 1}c]")
                else:
                    filters.append(
                        f"[{label}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,trim=start={start}:duration={duration:.3f},"
                        f"setpts=PTS-STARTPTS[v{v_index - 1}c]"
                    )
                    video_labels.append(f"[v{v_index - 1}c]")
            elif kind in ("voice", "music", "sfx"):
                audio_inputs.append(["-i", path])
                label = f"a{a_index}"
                a_index += 1
                volume_db = float(clip.get("volume_db", 0.0))
                filter_part = f"atrim=start={start}:duration={duration:.3f},asetpts=PTS-STARTPTS"
                if volume_db:
                    filter_part += f",volume={volume_db}dB"
                filters.append(f"[{label}:a]{filter_part}[a{a_index - 1}c]")
                audio_labels.append(f"[a{a_index - 1}c]")

    if not video_labels:
        video_labels.append("color=c=black:s=" + str(width) + "x" + str(height) + ":d=1")
        filters.append("null")
        video_labels = ["[0:v]"]
        video_inputs = []

    duration = float(timeline.get("duration", 1.0))
    if not audio_labels:
        audio_labels.append("anullsrc=channel_layout=stereo:sample_rate=48000")
        filters.append("null")
        audio_labels = ["[1:a]" if video_inputs else "[0:a]"]
        audio_inputs = []
    filter_complex = ";".join(filters)
    concat_video = "".join(video_labels)
    concat_audio = "".join(audio_labels)
    if len(video_labels) == 1:
        vout = video_labels[0]
    else:
        vout = "[vout]"
        filter_complex += f";{concat_video}concat=n={len(video_labels)}:v=1:a=0[vout]"
    if len(audio_labels) == 1:
        aout = audio_labels[0]
    else:
        aout = "[aout]"
        filter_complex += f";{concat_audio}amix=inputs={len(audio_labels)}:normalize=0[aout]"
    filter_complex += f";[vout]fps={fps},format=yuv420p[vfinal]"

    output_dir = settings.media_dir / project_id / "renders"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{uuid.uuid4().hex}.mp4"
    command = [
        str(settings.ffmpeg_path),
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={width}x{height}:r={fps}:d={max(duration, 1.0)}",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=48000",
    ]
    for item in video_inputs:
        command.extend(item)
    for item in audio_inputs:
        command.extend(item)
    command.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "[vfinal]",
            "-map",
            aout,
            "-t",
            f"{duration:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-c:a",
            "aac",
            "-shortest",
            str(output),
        ]
    )
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    total_duration = max(duration, 1.0)
    try:
        assert process.stdout is not None
        for line in process.stdout:
            if should_cancel and should_cancel():
                process.terminate()
                raise RuntimeError("render canceled")
            if line.startswith("out_time_ms="):
                try:
                    out_ms = int(line.strip().split("=", 1)[1])
                    ratio = min(1.0, (out_ms / 1000.0) / total_duration)
                    if progress:
                        progress(ratio)
                except ValueError:
                    pass
        stderr = process.stderr.read() if process.stderr else ""
        return_code = process.wait(timeout=60)
    except Exception:
        process.kill()
        raise
    if return_code != 0:
        raise RuntimeError(f"ffmpeg render failed: {stderr[-2000:]}")
    return output.as_posix(), duration
