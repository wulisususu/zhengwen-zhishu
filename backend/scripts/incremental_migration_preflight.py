"""Run incremental PPT schema creation twice against a disposable SQLite copy."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine

import app.database as database


def snapshot(path: Path) -> tuple[dict[str, int], str]:
    with sqlite3.connect(path) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        counts = {
            name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in tables
        }
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    return counts, integrity


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    target = args.target.resolve(strict=False)
    if source == target:
        raise SystemExit("target must be a disposable copy")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.exists():
        target.unlink()

    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    target.chmod(0o600)

    before, before_integrity = snapshot(target)
    database.engine = create_engine(
        f"sqlite:///{target}", connect_args={"check_same_thread": False}
    )
    database.init_db()
    database.init_db()
    after, after_integrity = snapshot(target)

    existing_unchanged = all(after.get(name) == count for name, count in before.items())
    passed = existing_unchanged and before_integrity == after_integrity == "ok"
    new_tables = sorted(set(after) - set(before))
    print(f"MIGRATION_PREFLIGHT={'PASS' if passed else 'FAIL'}")
    print(f"INTEGRITY_BEFORE={before_integrity}")
    print(f"INTEGRITY_AFTER={after_integrity}")
    print(f"EXISTING_ROWS_UNCHANGED={str(existing_unchanged).lower()}")
    print(f"NEW_TABLES={','.join(new_tables)}")
    print("NEW_ROW_COUNTS=" + ",".join(f"{name}:{after[name]}" for name in new_tables))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
