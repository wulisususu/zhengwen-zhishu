from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from pathlib import Path
import logging
import os

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

        # --- 最小角色控制：users.is_admin（SQLite 无法加 NOT NULL 列，用默认值兜住旧数据）---
        _add_column_if_missing(conn, "users", "is_admin", "is_admin BOOLEAN NOT NULL DEFAULT 0")
        _bootstrap_admin(conn)


def _bootstrap_admin(conn) -> None:
    """保证系统里至少有一个管理员。

    优先用 security.admin_username 指定；未配置则取 id 最小的用户（通常是首个账号）。
    只在「当前没有任何管理员」时执行，不会覆盖人工设置。
    """
    try:
        existing = conn.exec_driver_sql("SELECT COUNT(*) FROM users WHERE is_admin = 1").scalar()
        if existing and int(existing) > 0:
            return
        username = ""
        try:
            from app.config import get_config

            username = str(((get_config() or {}).get("security") or {}).get("admin_username") or "").strip()
        except Exception:
            username = ""
        username = username or str(os.getenv("ADMIN_USERNAME") or "").strip()
        if username:
            row = conn.exec_driver_sql("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if row is None:
                logger.warning("security.admin_username=%s 不存在，跳过管理员引导", username)
                return
            admin_id = row[0]
        else:
            row = conn.exec_driver_sql("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
            if row is None:
                return  # 还没有任何用户，等注册后再引导
            admin_id = row[0]
        conn.exec_driver_sql("UPDATE users SET is_admin = 1 WHERE id = ?", (admin_id,))
        logger.warning("已将用户 id=%s 引导为管理员（后续请在 /users 中维护角色）", admin_id)
    except Exception as exc:  # 引导失败不能阻断启动
        logger.error("管理员引导失败：%s", exc)


def init_db():
    from app import models  # noqa
    from app.policy import models as _policy_models  # noqa: F401
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
