"""Dependencies: auth, db session."""
import os

from fastapi import Cookie, Depends, HTTPException, Header, Query
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from passlib.context import CryptContext
from datetime import datetime, timedelta
from app.database import get_db
from app.config import get_config
from app.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(user_id: int) -> str:
    cfg = get_config()["jwt"]
    payload = {
        "sub": str(user_id),
        "exp": datetime.utcnow() + timedelta(minutes=cfg["expire_minutes"]),
    }
    return jwt.encode(payload, cfg["secret"], algorithm=cfg["algorithm"])


def _extract_token(authorization: str | None, cookie_token: str | None, query_token: str | None) -> str:
    if authorization and authorization.startswith("Bearer "):
        return authorization.split(" ", 1)[1]
    if cookie_token:
        return cookie_token
    if query_token:
        return query_token
    raise HTTPException(status_code=401, detail="Missing token")


def _extract_bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def _desktop_internal_token() -> str:
    return str(os.getenv("DESKTOP_INTERNAL_TOKEN") or "").strip()


def get_current_user(
    authorization: str = Header(None),
    mqw_token: str | None = Cookie(None),
    token: str | None = Query(None),
    db: Session = Depends(get_db),
) -> User:
    jwt_token = _extract_token(authorization, mqw_token, token)
    try:
        cfg = get_config()["jwt"]
        payload = jwt.decode(jwt_token, cfg["secret"], algorithms=[cfg["algorithm"]])
        user_id = int(payload["sub"])
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """管理员专用依赖。服务端校验，不依赖前端隐藏按钮。"""
    if not bool(getattr(user, "is_admin", False)):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def optional_user(
    authorization: str = Header(None),
    mqw_token: str | None = Cookie(None),
    token: str | None = Query(None),
    db: Session = Depends(get_db),
) -> User | None:
    if not authorization and not mqw_token and not token:
        return None
    try:
        return get_current_user(authorization, mqw_token, token, db)
    except HTTPException:
        return None


def require_asr_access(
    authorization: str = Header(None),
    mqw_token: str | None = Cookie(None),
    token: str | None = Query(None),
    db: Session = Depends(get_db),
) -> bool:
    try:
        get_current_user(authorization, mqw_token, token, db)
        return True
    except HTTPException as exc:
        desktop_token = _desktop_internal_token()
        bearer_token = _extract_bearer_token(authorization)
        if desktop_token and bearer_token == desktop_token:
            return True
        raise exc
