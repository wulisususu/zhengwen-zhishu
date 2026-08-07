from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from pathlib import Path
import logging

DB_PATH = Path(__file__).parent.parent / "data" / "app.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


logger = logging.getLogger(__name__)


def _table_columns(conn, table_name: str) -> set[str]:
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


def _add_column_if_missing(conn, table_name: str, column_name: str, ddl: str) -> None:
    if column_name in _table_columns(conn, table_name):
        return
    logger.info("Adding missing column %s.%s", table_name, column_name)
    conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")


def _run_startup_migrations() -> None:
    with engine.begin() as conn:
        
        # Create ppt_structured_workspaces table if not exists
        conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS ppt_structured_workspaces (
                workspace_id TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'builtin',
                source_template_id TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                version INTEGER NOT NULL DEFAULT 1,
                canvas TEXT NOT NULL DEFAULT 'ppt169',
                theme_json TEXT NOT NULL DEFAULT '{}',
                master_manifest_json TEXT NOT NULL DEFAULT '[]',
                layout_manifest_json TEXT NOT NULL DEFAULT '[]',
                placeholder_manifest_json TEXT NOT NULL DEFAULT '[]',
                asset_manifest_json TEXT NOT NULL DEFAULT '[]',
                validation_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_user_id) REFERENCES users (id)
            )
        """)
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_ppt_structured_workspaces_owner ON ppt_structured_workspaces(owner_user_id)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_ppt_structured_workspaces_source_type ON ppt_structured_workspaces(source_type)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_ppt_structured_workspaces_status ON ppt_structured_workspaces(status)")

        
        # Create ppt_structured_workspaces table if not exists
        conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS ppt_structured_workspaces (
                workspace_id TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'builtin',
                source_template_id TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                version INTEGER NOT NULL DEFAULT 1,
                canvas TEXT NOT NULL DEFAULT 'ppt169',
                theme_json TEXT NOT NULL DEFAULT '{}',
                master_manifest_json TEXT NOT NULL DEFAULT '[]',
                layout_manifest_json TEXT NOT NULL DEFAULT '[]',
                placeholder_manifest_json TEXT NOT NULL DEFAULT '[]',
                asset_manifest_json TEXT NOT NULL DEFAULT '[]',
                validation_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_user_id) REFERENCES users (id)
            )
        """)
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_ppt_structured_workspaces_owner ON ppt_structured_workspaces(owner_user_id)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_ppt_structured_workspaces_source_type ON ppt_structured_workspaces(source_type)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_ppt_structured_workspaces_status ON ppt_structured_workspaces(status)")

        for column_name, ddl in (
            ("owner_user_id", "owner_user_id INTEGER"),
            ("project_id", "project_id TEXT"),
            ("task_id", "task_id TEXT"),
            ("real_path", "real_path TEXT"),
            ("mime_type", "mime_type TEXT"),
            ("size", "size INTEGER"),
            ("sha256", "sha256 TEXT"),
            ("expires_at", "expires_at DATETIME"),
        ):
            _add_column_if_missing(conn, "files", column_name, ddl)
        conn.exec_driver_sql(
            """
            UPDATE files
            SET owner_user_id = user_id,
                real_path = filepath,
                mime_type = CASE
                    WHEN filetype = '.pptx' THEN 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
                    ELSE NULL
                END,
                size = filesize
            WHERE owner_user_id IS NULL
            """
        )
        _add_column_if_missing(
            conn,
            "conversations",
            "workflow_type",
            "workflow_type TEXT NOT NULL DEFAULT 'chat'",
        )
        _add_column_if_missing(
            conn,
            "messages",
            "workflow_type",
            "workflow_type TEXT NOT NULL DEFAULT 'chat'",
        )
        _add_column_if_missing(
            conn,
            "messages",
            "intent_type",
            "intent_type TEXT DEFAULT ''",
        )
        _add_column_if_missing(
            conn,
            "messages",
            "metadata_json",
            "metadata_json TEXT DEFAULT ''",
        )
        _add_column_if_missing(
            conn,
            "document_tasks",
            "conversation_id",
            "conversation_id INTEGER",
        )
        _add_column_if_missing(
            conn,
            "document_tasks",
            "message_id",
            "message_id INTEGER",
        )
        _add_column_if_missing(
            conn,
            "document_tasks",
            "workflow_type",
            "workflow_type TEXT NOT NULL DEFAULT 'document'",
        )
        _add_column_if_missing(
            conn,
            "ppt_incremental_tasks",
            "source_refs_json",
            "source_refs_json TEXT DEFAULT '{}'",
        )

        conn.exec_driver_sql(
            """
            UPDATE conversations
            SET workflow_type = 'document'
            WHERE id IN (
                SELECT DISTINCT conversation_id
                FROM document_tasks
                WHERE conversation_id IS NOT NULL
            )
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE conversations
            SET workflow_type = 'document'
            WHERE id IN (
                SELECT DISTINCT conversation_id
                FROM messages
                WHERE content LIKE '%[[DOC_TASK]]%'
            )
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE messages
            SET workflow_type = COALESCE(
                (SELECT workflow_type FROM conversations WHERE conversations.id = messages.conversation_id),
                'chat'
            )
            WHERE workflow_type IS NULL OR workflow_type = '' OR workflow_type = 'chat'
            """
        )


def init_db():
    from app import models  # noqa
    Base.metadata.create_all(bind=engine)
    _run_startup_migrations()
    # --- P3-B Guided Strategist: ensure guided_projects table exists (idempotent) ---
    # run_migrations() imports the engine lazily to avoid a circular import.
    from app.PPT_master.guided_migration import run_migrations  # noqa: E402
    from app.PPT_master.animation_migration import run_migrations as run_anim_migrations  # noqa: E402  (P4)
    run_anim_migrations()
    run_migrations()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
