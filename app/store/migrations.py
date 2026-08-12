"""Alembic bootstrap for fresh and pre-Alembic databases."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

BASELINE_REVISION = "20260811_0001"
HEAD_REVISION = "20260812_0013"
ROOT_DIR = Path(__file__).resolve().parents[2]


def _config() -> Config:
    config = Config(str(ROOT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT_DIR / "alembic"))
    return config


def upgrade_database(engine: Engine) -> None:
    with engine.begin() as connection:
        table_names = set(inspect(connection).get_table_names())
        config = _config()
        config.attributes["connection"] = connection
        legacy_schema = (
            "alembic_version" not in table_names
            and "projects" in table_names
            and "artifacts" in table_names
        )
        if legacy_schema:
            command.stamp(config, BASELINE_REVISION)
        command.upgrade(config, "head")
