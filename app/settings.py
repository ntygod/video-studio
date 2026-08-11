# -*- coding: utf-8 -*-
"""Application settings and canonical filesystem layout."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

try:
    import sys
    from pathlib import Path

    _candidate = Path(sys.executable).parent / "static_ffmpeg.exe"
    FFMPEG_PATH = str(_candidate) if _candidate.exists() else "ffmpeg"
    _probe_candidate = Path(sys.executable).parent / "static_ffprobe.exe"
    FFPROBE_PATH = str(_probe_candidate) if _probe_candidate.exists() else "ffprobe"
except Exception:
    FFMPEG_PATH = "ffmpeg"
    FFPROBE_PATH = "ffprobe"


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VIDEO_STUDIO_",
        env_file=BASE_DIR / ".env",
        extra="ignore",
    )

    app_name: str = "Video Studio"
    app_version: str = "1.0.0"
    schema_version: int = 1
    data_dir: Path = BASE_DIR / "data"
    database_url: str = ""
    media_dir: Path = BASE_DIR / "data" / "media"
    work_dir: Path = BASE_DIR / "data" / "work"
    ffmpeg_path: str = FFMPEG_PATH
    ffprobe_path: str = FFPROBE_PATH

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'studio.db').as_posix()}"

    def ensure_directories(self) -> None:
        for directory in (self.data_dir, self.media_dir, self.work_dir):
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def media_store(self):
        from .store.media_store import MediaStore

        return MediaStore(
            self.media_dir,
            ffmpeg_path=self.ffmpeg_path,
            ffprobe_path=self.ffprobe_path,
        )


settings = Settings()
settings.ensure_directories()
