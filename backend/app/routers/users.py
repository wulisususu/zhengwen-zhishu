"""User CRUD."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.schemas import UserCreate, UserOut
from app.deps import get_current_user, hash_password
from app.errors import ok, fail, ERR_PARAM, ERR_NOT_FOUND

router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
def list_users(db: Session = Depends(get_db), _=Depends(get_current_user)):
    users = db.query(User).order_by(User.id).all()
    return ok(data=[UserOut.model_validate(u).model_dump() for u in users])


@router.post("")
def create_user(body: UserCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    if db.query(User).filter(User.username == body.username).first():
        return fail(ERR_PARAM, "username already exists")
    user = User(username=body.username, password_hash=hash_password(body.password), nickname=body.nickname)
    db.add(user)
    db.commit()
    db.refresh(user)
    return ok(data=UserOut.model_validate(user).model_dump())


@router.put("/{user_id}")
def update_user(user_id: int, body: UserCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return fail(ERR_NOT_FOUND, "user not found")
    user.nickname = body.nickname or user.nickname
    if body.password:
        user.password_hash = hash_password(body.password)
    db.commit()
    return ok(data=UserOut.model_validate(user).model_dump())


@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return fail(ERR_NOT_FOUND, "user not found")
    db.delete(user)
    db.commit()
    return ok(message="deleted")
