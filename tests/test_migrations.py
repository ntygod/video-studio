import json

from sqlalchemy import create_engine, inspect, text

from app.store import dependency_models  # noqa: F401
from app.store import models  # noqa: F401
from app.store import operation_models  # noqa: F401
from app.store import regeneration_models  # noqa: F401
from app.store import regeneration_replan_models  # noqa: F401
from app.store import task_runtime_models  # noqa: F401
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
        inspector = inspect(database.engine)
        tables = set(inspector.get_table_names())
        assert {
            "projects",
            "creative_units",
            "artifacts",
            "artifact_versions",
            "jobs",
            "operation_logs",
            "artifact_dependencies",
            "asset_dependencies",
            "artifact_provenance",
            "artifact_freshness",
            "regeneration_plans",
            "regeneration_plan_steps",
            "regeneration_plan_replans",
            "runtime_plans",
            "runtime_tasks",
            "runtime_task_attempts",
            "runtime_task_events",
            "alembic_version",
        } <= tables
        operation_columns = {
            item["name"]
            for item in inspector.get_columns(
                "operation_logs"
            )
        }
        assert {
            "reverted_by_operation_id",
            "reverted_at",
        } <= operation_columns
        asset_dependency_columns = {
            item["name"]
            for item in inspector.get_columns(
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
            for item in inspector.get_columns(
                "regeneration_plans"
            )
        }
        assert {
            "snapshot_sha256",
            "status",
            "execution_attempt",
            "started_at",
            "completed_at",
        } <= plan_columns
        step_columns = {
            item["name"]
            for item in inspector.get_columns(
                "regeneration_plan_steps"
            )
        }
        assert {
            "expected_version_id",
            "depends_on_artifact_ids_json",
            "job_id",
            "claim_token",
            "claim_owner",
            "claim_until",
            "claim_attempt",
            "execution_attempt",
            "attempt_history_json",
            "input_json",
            "result_json",
        } <= step_columns
        replan_columns = {
            item["name"]
            for item in inspector.get_columns(
                "regeneration_plan_replans"
            )
        }
        assert {
            "source_plan_id",
            "target_plan_id",
            "source_status",
            "source_execution_attempt",
            "target_snapshot_sha256",
            "reason",
        } <= replan_columns
        runtime_plan_columns = {
            item["name"]
            for item in inspector.get_columns(
                "runtime_plans"
            )
        }
        assert {
            "kind",
            "subject_type",
            "subject_id",
            "idempotency_key",
            "status",
            "event_seq",
            "policy_json",
            "budget_json",
            "usage_json",
        } <= runtime_plan_columns
        runtime_task_columns = {
            item["name"]
            for item in inspector.get_columns(
                "runtime_tasks"
            )
        }
        assert {
            "task_key",
            "task_type",
            "depends_on_task_ids_json",
            "attempt_count",
            "max_attempts",
            "timeout_seconds",
            "available_at",
            "checkpoint_json",
            "claim_token",
            "claim_owner",
            "claim_until",
            "claim_attempt",
        } <= runtime_task_columns
        runtime_attempt_columns = {
            item["name"]
            for item in inspector.get_columns(
                "runtime_task_attempts"
            )
        }
        assert {
            "task_id",
            "attempt",
            "status",
            "worker_id",
            "claim_token",
            "checkpoint_json",
            "heartbeat_at",
            "lease_until",
            "retryable",
        } <= runtime_attempt_columns
        step_indexes = {
            item["name"]
            for item in inspector.get_indexes(
                "regeneration_plan_steps"
            )
        }
        assert "ix_regeneration_steps_claimable" in step_indexes
        runtime_task_indexes = {
            item["name"]
            for item in inspector.get_indexes(
                "runtime_tasks"
            )
        }
        assert "ix_runtime_tasks_claimable" in runtime_task_indexes
        replan_unique = {
            item["name"]
            for item in inspector.get_unique_constraints(
                "regeneration_plan_replans"
            )
        }
        assert {
            "uq_regeneration_replan_source",
            "uq_regeneration_replan_target",
        } <= replan_unique
        runtime_unique = {
            item["name"]
            for item in inspector.get_unique_constraints(
                "runtime_tasks"
            )
        }
        assert "uq_runtime_task_plan_key" in runtime_unique
    finally:
        database.engine.dispose()


def test_pre_alembic_database_is_stamped_then_upgraded(tmp_path):
    path = tmp_path / "legacy.db"
    url = _url(path)
    legacy_engine = create_engine(url, future=True)
    Base.metadata.create_all(legacy_engine)
    with legacy_engine.begin() as connection:
        for table in (
            "runtime_task_events",
            "runtime_task_attempts",
            "runtime_tasks",
            "runtime_plans",
            "regeneration_plan_replans",
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
        inspector = inspect(database.engine)
        tables = set(inspector.get_table_names())
        assert {
            "operation_logs",
            "artifact_dependencies",
            "asset_dependencies",
            "artifact_provenance",
            "artifact_freshness",
            "regeneration_plans",
            "regeneration_plan_steps",
            "regeneration_plan_replans",
            "runtime_plans",
            "runtime_tasks",
            "runtime_task_attempts",
            "runtime_task_events",
        } <= tables
        plan_columns = {
            item["name"]
            for item in inspector.get_columns(
                "regeneration_plans"
            )
        }
        assert "execution_attempt" in plan_columns
        step_columns = {
            item["name"]
            for item in inspector.get_columns(
                "regeneration_plan_steps"
            )
        }
        assert {
            "claim_token",
            "claim_owner",
            "claim_until",
            "claim_attempt",
            "execution_attempt",
            "attempt_history_json",
        } <= step_columns
        runtime_task_columns = {
            item["name"]
            for item in inspector.get_columns(
                "runtime_tasks"
            )
        }
        assert {
            "attempt_count",
            "max_attempts",
            "claim_token",
            "checkpoint_json",
        } <= runtime_task_columns
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
