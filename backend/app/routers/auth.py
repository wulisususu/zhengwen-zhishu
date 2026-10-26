"""Auth: register, login, me."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import ROLE_ENTRY_PREFIX, User
from app.schemas import UserCreate, UserLogin, TokenOut, UserOut
from app.deps import hash_password, verify_password, create_token, get_current_user
from app.errors import ok, fail, ERR_AUTH, ERR_PARAM

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
def register(body: UserCreate, db: Session = Depends(get_db)):
    if body.username.lower().startswith(ROLE_ENTRY_PREFIX):
        return fail(ERR_PARAM, "该用户名为系统保留")
    if db.query(User).filter(User.username == body.username).first():
        return fail(ERR_PARAM, "用户名已存在")
    user = User(username=body.username, password_hash=hash_password(body.password), nickname=body.nickname)
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_token(user.id)
    return ok(data=TokenOut(access_token=token).model_dump())


@router.post("/login")
def login(body: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or user.gov_role or not verify_password(body.password, user.password_hash):
        return fail(ERR_AUTH, "用户名或密码错误")
    token = create_token(user.id)
    return ok(data=TokenOut(access_token=token).model_dump())


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return ok(data=UserOut.model_validate(user).model_dump())


@router.post("/refresh")
def refresh(user: User = Depends(get_current_user)):
    token = create_token(user.id)
    return ok(data=TokenOut(access_token=token).model_dump())
