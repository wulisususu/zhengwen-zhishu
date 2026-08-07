"""Pydantic schemas for request/response validation."""
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime


# ---- Unified Response ----
class R(BaseModel):
    code: int = 0
    message: str = "ok"
    data: Any = None
    trace_id: str = ""


# ---- Auth ----
class UserCreate(BaseModel):
    username: str
    password: str
    nickname: str = ""


class UserLogin(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str
    nickname: str
    created_at: datetime
    model_config = {"from_attributes": True}


# ---- Chat ----
class ConversationCreate(BaseModel):
    title: str = "新对话"
    workflow_type: str = "chat"


class ConversationOut(BaseModel):
    id: int
    title: str
    workflow_type: str = "chat"
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class MessageCreate(BaseModel):
    content: str
    msg_type: str = "text"


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    msg_type: str
    workflow_type: str = "chat"
    intent_type: str = ""
    metadata_json: str = ""
    created_at: datetime
    model_config = {"from_attributes": True}


# ---- Settings ----
class SettingUpdate(BaseModel):
    key: str
    value: str
    description: str = ""
