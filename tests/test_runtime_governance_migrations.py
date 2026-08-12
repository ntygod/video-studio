from sqlalchemy import inspect, text

from app.store.database import Database
from app.store.migrations import HEAD_REVISION


def test_runtime_governance_migration_installs_policy_and_budget_tables(tmp_path):
    database = Database(
        f"sqlite:///{(tmp_path / 'runtime-governance.db').as_posix()}"
    )
    try:
        database.create_schema()
        inspector = inspect(database.engine)
        tables = set(inspector.get_table_names())
        assert {
            "runtime_policy_decisions",
            "runtime_budget_ledgers",
            "runtime_budget_task_usage",
            "runtime_budget_consumptions",
        } <= tables
        with database.engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert revision == HEAD_REVISION == "20260812_0012"
        decision_unique = {
            item["name"]
            for item in inspector.get_unique_constraints(
                "runtime_policy_decisions"
            )
        }
        consumption_unique = {
            item["name"]
            for item in inspector.get_unique_constraints(
                "runtime_budget_consumptions"
            )
        }
        assert "uq_runtime_policy_plan_action" in decision_unique
        assert "uq_runtime_budget_plan_consumption" in consumption_unique
    finally:
        database.engine.dispose()
