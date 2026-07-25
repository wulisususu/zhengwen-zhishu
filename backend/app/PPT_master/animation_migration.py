"""P4 Animation DB migration — idempotent (CREATE IF NOT EXISTS).

Called from app.database.init_db() alongside P3-B guided_migration.
"""

from __future__ import annotations

import logging
from app.database import engine

logger = logging.getLogger(__name__)


def ensure_animation_tables():
    """Idempotent: create ppt_animation_manifests if not exists."""
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS ppt_animation_manifests (
                manifest_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                document_revision INTEGER NOT NULL,
                animation_revision INTEGER NOT NULL DEFAULT 1,
                animations_json TEXT NOT NULL DEFAULT '{}',
                sha256 TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                UNIQUE (project_id, animation_revision)
            )
        """)
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_anim_manifest_project "
            "ON ppt_animation_manifests(project_id)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_anim_manifest_user "
            "ON ppt_animation_manifests(user_id)"
        )
        logger.info("P4 animation manifest table ready")


def run_migrations():
    """Entry point called from app.database.init_db()."""
    ensure_animation_tables()
