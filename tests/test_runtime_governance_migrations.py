from sqlalchemy import inspect, text

from app.store.database import Database
from app.store.migrations import HEAD_REVISION


def test_runtime_governance_migration_installs_policy_budget_cost_and_request_tables(
    tmp_path,
):
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
            "runtime_cost_entries",
            "runtime_provider_requests",
            "model_pricing_profiles",
        } <= tables
        with database.engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert revision == HEAD_REVISION == "20260813_0015"
        decision_columns = {
            item["name"]
            for item in inspector.get_columns(
                "runtime_policy_decisions"
            )
        }
        decision_indexes = {
            item["name"]
            for item in inspector.get_indexes(
                "runtime_policy_decisions"
            )
        }
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
        cost_unique = {
            item["name"]
            for item in inspector.get_unique_constraints(
                "runtime_cost_entries"
            )
        }
        request_unique = {
            item["name"]
            for item in inspector.get_unique_constraints(
                "runtime_provider_requests"
            )
        }
        request_indexes = {
            item["name"]
            for item in inspector.get_indexes(
                "runtime_provider_requests"
            )
        }
        assert "expires_at" in decision_columns
        assert "ix_runtime_policy_pending_expiry" in decision_indexes
        assert "uq_runtime_policy_plan_action" in decision_unique
        assert "uq_runtime_budget_plan_consumption" in consumption_unique
        assert "uq_runtime_cost_plan_usage" in cost_unique
        assert "uq_runtime_provider_request_plan_key" in request_unique
        assert "ix_runtime_provider_requests_status_updated" in request_indexes
    finally:
        database.engine.dispose()
