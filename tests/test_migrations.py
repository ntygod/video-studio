import json

from sqlalchemy import create_engine, inspect, text

from app.store import models  # noqa: F401
from app.store.database import Base, Database
from app.store.migrations import BASELINE_REVISION


def _url(path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _revision(database: Database) -> str:
    with database.engine.connect() as connection:
        return connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()


def test_fresh_database_runs_alembic_baseline(tmp_path):
    database = Database(_url(tmp_path / "fresh.db"))
    try:
        database.create_schema()
        assert _revision(database) == BASELINE_REVISION
        tables = set(inspect(database.engine).get_table_names())
        assert {
            "projects",
            "creative_units",
            "artifacts",
            "artifact_versions",
            "jobs",
            "alembic_version",
        } <= tables
    finally:
        database.engine.dispose()


def test_pre_alembic_database_is_stamped_without_losing_data(tmp_path):
    path = tmp_path / "legacy.db"
    url = _url(path)
    legacy_engine = create_engine(url, future=True)
    Base.metadata.create_all(legacy_engine)
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO projects(
                    id, title, project_type, workflow_id, stage,
                    brief_json, bible_json, settings_json, custom_json,
                    revision, created_at, updated_at
                )
                VALUES(
                    :id, :title, 'freeform', 'freeform', 'brief',
                    :brief, :bible, :settings, '{}',
                    1, 1.0, 1.0
                )
                """
            ),
            {
                "id": "legacy-project",
                "title": "不能丢失",
                "brief": json.dumps({}),
                "bible": json.dumps({}),
                "settings": json.dumps({}),
            },
        )
    legacy_engine.dispose()

    database = Database(url)
    try:
        database.create_schema()
        assert _revision(database) == BASELINE_REVISION
        with database.engine.connect() as connection:
            title = connection.execute(
                text(
                    "SELECT title FROM projects "
                    "WHERE id='legacy-project'"
                )
            ).scalar_one()
        assert title == "不能丢失"
    finally:
        database.engine.dispose()
