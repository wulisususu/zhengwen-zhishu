"""P3-B Guided Strategist — idempotent schema migration for guided_projects.

OWNER: Sub1.

Pure DDL. Safe to call at every startup:
  1. ``CREATE TABLE IF NOT EXISTS`` (portable, dialect-aware) of guided_projects.
  2. Column-add-if-missing guard for the rare case that an OLDER
     guided_projects table exists with fewer columns (partial earlier schema).

It MUST NOT drop, alter, or touch any existing PPT table.

Importing ``GuidedProject`` is done lazily inside functions to avoid a circular
import (``guided_models`` -> ``app.database.Base``).
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateColumn


def ensure_guided_tables(engine) -> None:
    """Idempotently create the guided_projects table and add any missing columns.

    ``engine`` is a SQLAlchemy Engine. Safe to call repeatedly.
    """
    from app.PPT_master.guided_models import GuidedProject

    # 1) Create table if it does not already exist (portable, dialect-aware).
    GuidedProject.__table__.create(engine, checkfirst=True)

    # 2) Safety guard: add any columns missing from an older partial schema.
    inspector = inspect(engine)
    existing_cols = {c["name"] for c in inspector.get_columns("guided_projects")}
    missing = [
        col
        for col in GuidedProject.__table__.columns
        if col.name not in existing_cols and not col.primary_key
    ]
    if missing:
        with engine.begin() as conn:
            for col in missing:
                # Render portable column DDL via CreateColumn (SQLAlchemy 2.x).
                # Drop NOT NULL from the ALTER so existing rows are not rejected;
                # the full constraint is enforced on freshly created tables.
                ddl = str(CreateColumn(col).compile(dialect=engine.dialect))
                ddl = ddl.replace(" NOT NULL", "")
                conn.execute(text(f"ALTER TABLE guided_projects ADD COLUMN {ddl}"))


def run_migrations() -> None:
    """Startup entry point. Imports the engine lazily to break the
    app.database <-> guided_migration import cycle."""
    from app.database import engine

    ensure_guided_tables(engine)
