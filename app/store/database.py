from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str):
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, connect_args=connect_args, future=True)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._configure_sqlite)
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
            autoflush=False,
        )

    @staticmethod
    def _configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    def create_schema(self) -> None:
        from . import dependency_models  # noqa: F401
        from . import models  # noqa: F401
        from . import operation_models  # noqa: F401
        from . import regeneration_models  # noqa: F401
        from . import regeneration_replan_models  # noqa: F401
        from .migrations import upgrade_database

        upgrade_database(self.engine)
        if str(self.engine.url).startswith("sqlite"):
            self._ensure_model_default_column()
            self._create_fts()

    def _ensure_model_default_column(self) -> None:
        """旧库补 is_default 列；Alembic baseline 之前的兼容入口。"""
        with self.engine.begin() as conn:
            columns = {
                row[1]
                for row in conn.execute(text("PRAGMA table_info(model_profiles)"))
            }
            if columns and "is_default" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE model_profiles "
                        "ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT 0"
                    )
                )

    def _create_fts(self) -> None:
        """FTS5 虚拟表 + 同步触发器。trigram 分词器面向中文。"""
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS units_fts USING fts5("
                    "unit_id UNINDEXED, project_id UNINDEXED, title, summary, continuity_summary,"
                    "tokenize='trigram')"
                )
            )
            conn.execute(
                text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS artifacts_fts USING fts5("
                    "artifact_id UNINDEXED, project_id UNINDEXED, unit_id UNINDEXED, name, body,"
                    "tokenize='trigram')"
                )
            )
            conn.execute(
                text(
                    "CREATE TRIGGER IF NOT EXISTS trg_units_fts_insert "
                    "AFTER INSERT ON creative_units BEGIN "
                    "INSERT INTO units_fts(unit_id, project_id, title, summary, continuity_summary) "
                    "VALUES (new.id, new.project_id, new.title, new.summary, new.continuity_summary); END"
                )
            )
            conn.execute(
                text(
                    "CREATE TRIGGER IF NOT EXISTS trg_units_fts_update "
                    "AFTER UPDATE ON creative_units BEGIN "
                    "DELETE FROM units_fts WHERE unit_id = old.id; "
                    "INSERT INTO units_fts(unit_id, project_id, title, summary, continuity_summary) "
                    "VALUES (new.id, new.project_id, new.title, new.summary, new.continuity_summary); END"
                )
            )
            conn.execute(
                text(
                    "CREATE TRIGGER IF NOT EXISTS trg_units_fts_delete "
                    "AFTER DELETE ON creative_units BEGIN "
                    "DELETE FROM units_fts WHERE unit_id = old.id; END"
                )
            )
            conn.execute(
                text(
                    "CREATE TRIGGER IF NOT EXISTS trg_artifacts_fts_insert "
                    "AFTER INSERT ON artifacts BEGIN "
                    "INSERT INTO artifacts_fts(artifact_id, project_id, unit_id, name, body) "
                    "VALUES (new.id, new.project_id, new.unit_id, new.name, ''); END"
                )
            )
            conn.execute(
                text(
                    "CREATE TRIGGER IF NOT EXISTS trg_artifacts_fts_update "
                    "AFTER UPDATE OF current_version_id, name, unit_id ON artifacts BEGIN "
                    "DELETE FROM artifacts_fts WHERE artifact_id = new.id; "
                    "INSERT INTO artifacts_fts(artifact_id, project_id, unit_id, name, body) "
                    "SELECT new.id, new.project_id, new.unit_id, new.name, "
                    "COALESCE((SELECT payload_json FROM artifact_versions WHERE id = new.current_version_id), ''); END"
                )
            )
            conn.execute(
                text(
                    "CREATE TRIGGER IF NOT EXISTS trg_artifacts_fts_delete "
                    "AFTER DELETE ON artifacts BEGIN "
                    "DELETE FROM artifacts_fts WHERE artifact_id = old.id; END"
                )
            )
            conn.execute(
                text(
                    "CREATE TRIGGER IF NOT EXISTS trg_artifact_versions_fts_update "
                    "AFTER UPDATE OF payload_json ON artifact_versions BEGIN "
                    "DELETE FROM artifacts_fts WHERE artifact_id = new.artifact_id; "
                    "INSERT INTO artifacts_fts(artifact_id, project_id, unit_id, name, body) "
                    "SELECT a.id, a.project_id, a.unit_id, a.name, new.payload_json "
                    "FROM artifacts a WHERE a.id = new.artifact_id; END"
                )
            )

    @contextmanager
    def session(self):
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def health(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
