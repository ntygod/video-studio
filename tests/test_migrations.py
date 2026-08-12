import json

from sqlalchemy import create_engine, inspect, text

from app.store import dependency_models  # noqa: F401
from app.store import models  # noqa: F401
from app.store import operation_models  # noqa: F401
from app.store import regeneration_models  # noqa: F401
from app.store.database import Base, Database
from app.store.migrations import BASELINE_REVISION, HEAD_REVISION


def _url(path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _revision(database: Database) -> str:
    with database.engine.connect() as connection:
        return connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()


def test_fresh_database_runs_all_migrations(tmp_path):
    database = Database(_url(tmp_path / "fresh.db"))
    try:
        database.create_schema()
        assert _revision(database) == HEAD_REVISION
        tables = set(inspect(database.engine).get_table_names())
        assert {
            "projects", "creative_units", "artifacts",
            "artifact_versions", "jobs", "operation_logs",
            "artifact_dependencies", "asset_dependencies",
            "artifact_provenance", "artifact_freshness",
            "regeneration_plans", "regeneration_plan_steps",
            "alembic_version",
        } <= tables
        operation_columns = {
            item["name"]
            for item in inspect(database.engine).get_columns("operation_logs")
        }
        assert {"reverted_by_operation_id", "reverted_at"} <= operation_columns
        asset_dependency_columns = {
            item["name"]
            for item in inspect(database.engine).get_columns(
                "asset_dependencies"
            )
        }
        assert {
            "upstream_asset_id",
            "upstream_asset_snapshot_json",
            "downstream_version_id",
        } <= asset_dependency_columns
        plan_columns = {
            item["name"]
            for item in inspect(database.engine).get_columns(
                "regeneration_plans"
            )
        }
        assert {
            "snapshot_sha256", "status", "started_at", "completed_at"
        } <= plan_columns
        step_columns = {
            item["name"]
            for item in inspect(database.engine).get_columns(
                "regeneration_plan_steps"
            )
        }
        assert {
            "expected_version_id", "depends_on_artifact_ids_json",
            "job_id", "input_json", "result_json",
        } <= step_columns
    finally:
        database.engine.dispose()


def test_pre_alembic_database_is_stamped_then_upgraded(tmp_path):
    path = tmp_path / "legacy.db"
    url = _url(path)
    legacy_engine = create_engine(url, future=True)
    Base.metadata.create_all(legacy_engine)
    with legacy_engine.begin() as connection:
        for table in (
            "regeneration_plan_steps",
            "regeneration_plans",
            "asset_dependencies",
            "artifact_freshness",
            "artifact_provenance",
            "artifact_dependencies",
            "operation_logs",
        ):
            connection.execute(text(f"DROP TABLE IF EXISTS {table}"))
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
        assert BASELINE_REVISION != HEAD_REVISION
        assert _revision(database) == HEAD_REVISION
        tables = set(inspect(database.engine).get_table_names())
        assert {
            "operation_logs", "artifact_dependencies",
            "asset_dependencies", "artifact_provenance",
            "artifact_freshness", "regeneration_plans",
            "regeneration_plan_steps",
        } <= tables
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
