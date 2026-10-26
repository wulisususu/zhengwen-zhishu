"""Role entry: no login page, the visitor picks 起草人 or 审核人.

This is role selection, not authentication. Anyone who can reach the server can
take either role, so the two role accounts get gov workflow rights only:
- never is_admin (users, settings, data purge, upgrades stay unreachable);
- unusable random password, so /auth/login cannot open them;
- excluded from the admin bootstrap (app/database.py);
- reserved usernames (ROLE_ENTRY_PREFIX), so registration cannot claim them.
Every existing backend check stays in force: drafts belong to their owner, the
reviewer cannot draft, and nobody approves their own document.

GET  /gov/entry  public  {enabled, roles}
POST /gov/entry  public  {role} -> {access_token, token_type, role, actor}
"""
import logging
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import create_token, hash_password
from app.errors import ok
from app.models import ROLE_ENTRY_PREFIX, User

logger = logging.getLogger("app.gov.entry")
router = APIRouter()

Role = Literal["drafter", "reviewer"]
ROLE_ACCOUNTS: dict[str, tuple[str, str, str]] = {
    "drafter": (ROLE_ENTRY_PREFIX + "drafter", "起草人", "起草通知、保存草稿、提交审核、查看审核结果"),
    "reviewer": (ROLE_ENTRY_PREFIX + "reviewer", "审核人", "审核他人送审的文稿、批准或退回、维护政策库"),
}


def entry_enabled() -> bool:
    try:
        from app.config import get_config
        section = (get_config() or {}).get("gov_entry") or {}
    except Exception:   # no config.yaml: role entry is the default way in
        section = {}
    return bool(section.get("enabled", True))


def ensure_role_user(db: Session, role: str) -> User:
    username, nickname, _ = ROLE_ACCOUNTS[role]
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        user = User(username=username, nickname=nickname, is_admin=False, gov_role=role,
                    password_hash=hash_password(secrets.token_urlsafe(32)))
        db.add(user)
        try:
            db.commit()
        except IntegrityError:   # another request created it first
            db.rollback()
            user = db.query(User).filter(User.username == username).first()
        else:
            db.refresh(user)
            logger.info("created role entry account role=%s id=%s", role, user.id)
    # Never adopt an account that is not exactly the role account (e.g. promoted to admin).
    if user is None or user.gov_role != role or user.is_admin:
        logger.error("role entry account conflict role=%s", role)
        raise HTTPException(409, "角色账号与已有账号冲突，请联系系统维护人员")
    return user


class EntryRequest(BaseModel):
    role: Role


@router.get("/entry")
def entry_options():
    return ok({"enabled": entry_enabled(),
               "roles": [{"role": r, "label": label, "description": desc}
                         for r, (_, label, desc) in ROLE_ACCOUNTS.items()]})


@router.post("/entry")
def enter(body: EntryRequest, db: Session = Depends(get_db)):
    if not entry_enabled():
        raise HTTPException(404, "角色入口未开启")
    user = ensure_role_user(db, body.role)
    from .service import actor
    return ok({"access_token": create_token(user.id), "token_type": "bearer", "role": body.role, "actor": actor(user)})
