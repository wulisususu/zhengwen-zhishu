"""User CRUD with minimal role control.

规则（服务端强制，前端隐藏按钮不算数）：
- 列表 / 新建 / 删除：仅 admin
- 修改：本人可改自己的昵称和密码；admin 可改任何人
- 只有 admin 能把账号设为管理员
- 不允许删除自己，不允许移除最后一个管理员
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import ROLE_ENTRY_PREFIX, User
from app.schemas import UserCreate, UserOut, UserSelfUpdate
from app.deps import get_current_user, require_admin, hash_password
from app.errors import ok, fail, ERR_PARAM, ERR_NOT_FOUND

router = APIRouter(prefix="/users", tags=["users"])


def _admin_count(db: Session) -> int:
    return db.query(User).filter(User.is_admin.is_(True)).count()


@router.get("")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    users = db.query(User).order_by(User.id).all()
    return ok(data=[UserOut.model_validate(u).model_dump() for u in users])


@router.post("")
def create_user(body: UserCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if body.username.lower().startswith(ROLE_ENTRY_PREFIX):
        return fail(ERR_PARAM, "username is reserved")
    if db.query(User).filter(User.username == body.username).first():
        return fail(ERR_PARAM, "username already exists")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        nickname=body.nickname,
        is_admin=bool(body.is_admin),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return ok(data=UserOut.model_validate(user).model_dump())


@router.put("/{user_id}")
def update_user(
    user_id: int,
    body: UserSelfUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return fail(ERR_NOT_FOUND, "user not found")

    is_self = target.id == current.id
    is_admin = bool(getattr(current, "is_admin", False))
    if not is_self and not is_admin:
        raise HTTPException(status_code=403, detail="只能修改自己的账号信息")

    # 只有管理员能改角色
    wants_role_change = body.is_admin is not None and bool(body.is_admin) != bool(target.is_admin)
    if target.gov_role and (body.is_admin is True or body.password):
        raise HTTPException(status_code=403, detail="角色入口账号不能设置密码或管理员权限")

    if wants_role_change:
        if not is_admin:
            raise HTTPException(status_code=403, detail="需要管理员权限才能修改角色")
        if target.is_admin and not body.is_admin and _admin_count(db) <= 1:
            return fail(ERR_PARAM, "不能移除最后一个管理员")

    if body.nickname:
        target.nickname = body.nickname
    if body.password:
        target.password_hash = hash_password(body.password)
    if wants_role_change:
        target.is_admin = bool(body.is_admin)
    db.commit()
    db.refresh(target)
    return ok(data=UserOut.model_validate(target).model_dump())


@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), current: User = Depends(require_admin)):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return fail(ERR_NOT_FOUND, "user not found")
    if target.id == current.id:
        return fail(ERR_PARAM, "不能删除当前登录账号")
    if target.is_admin and _admin_count(db) <= 1:
        return fail(ERR_PARAM, "不能删除最后一个管理员")
    db.delete(target)
    db.commit()
    return ok(message="deleted")
