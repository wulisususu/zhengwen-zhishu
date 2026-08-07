"""Safely remove users and artifacts created by incremental PPT smoke tests."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from sqlalchemy import create_engine, or_
from sqlalchemy.orm import sessionmaker

from app.models import File, PPTGenerationRequest, PPTIncrementalEvent, PPTIncrementalTask, User


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _project_root(real_path: str, projects_root: Path) -> Path:
    path = Path(real_path).resolve(strict=True)
    candidates = [path.parent, path.parent.parent]
    for candidate in candidates:
        if candidate.parent == projects_root and candidate.name.startswith("pptgen_"):
            if candidate.is_symlink():
                raise RuntimeError("smoke_project_symlink_forbidden")
            return candidate
    raise RuntimeError("smoke_artifact_outside_project_root")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="pptinc_smoke_")
    parser.add_argument("--database", type=Path, default=BACKEND_ROOT / "data" / "app.db")
    parser.add_argument(
        "--projects-root",
        type=Path,
        default=BACKEND_ROOT / "app" / "PPT_master" / "projects",
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.prefix.startswith("pptinc_smoke_") or len(args.prefix) < len("pptinc_smoke_"):
        raise SystemExit("unsafe smoke prefix")

    database = args.database.resolve(strict=True)
    projects_root = args.projects_root.resolve(strict=True)
    factory = sessionmaker(
        bind=create_engine(f"sqlite:///{database}", connect_args={"check_same_thread": False})
    )
    db = factory()
    project_roots: set[Path] = set()
    try:
        users = db.query(User).filter(User.username.like(args.prefix + "%")).all()
        user_ids = [user.id for user in users]
        if not user_ids:
            print("SMOKE_USERS=0")
            print("SMOKE_CLEANUP=NOTHING_TO_DO")
            return 0

        tasks = db.query(PPTIncrementalTask).filter(PPTIncrementalTask.user_id.in_(user_ids)).all()
        task_ids = [task.task_id for task in tasks]
        files = db.query(File).filter(
            or_(File.user_id.in_(user_ids), File.owner_user_id.in_(user_ids))
        ).all()
        for record in files:
            value = record.real_path or record.filepath
            if value and Path(value).exists():
                project_roots.add(_project_root(value, projects_root))

        counts = {
            "users": len(users),
            "tasks": len(tasks),
            "events": (
                db.query(PPTIncrementalEvent)
                .filter(PPTIncrementalEvent.task_id.in_(task_ids))
                .count()
                if task_ids
                else 0
            ),
            "legacy_requests": db.query(PPTGenerationRequest)
            .filter(PPTGenerationRequest.user_id.in_(user_ids))
            .count(),
            "files": len(files),
            "project_dirs": len(project_roots),
        }
        for key, value in counts.items():
            print(f"SMOKE_{key.upper()}={value}")
        if not args.execute:
            print("SMOKE_CLEANUP=DRY_RUN")
            return 0

        if task_ids:
            db.query(PPTIncrementalEvent).filter(
                PPTIncrementalEvent.task_id.in_(task_ids)
            ).delete(synchronize_session=False)
            db.query(PPTIncrementalTask).filter(
                PPTIncrementalTask.task_id.in_(task_ids)
            ).delete(synchronize_session=False)
        db.query(PPTGenerationRequest).filter(
            PPTGenerationRequest.user_id.in_(user_ids)
        ).delete(synchronize_session=False)
        db.query(File).filter(
            or_(File.user_id.in_(user_ids), File.owner_user_id.in_(user_ids))
        ).delete(synchronize_session=False)
        db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    for project in project_roots:
        shutil.rmtree(project)
    print("SMOKE_CLEANUP=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
