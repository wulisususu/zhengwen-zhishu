"""政策问答的状态标签与问答留痕。

政策与条款本身只存在既有政策库（T1，policy.db）中，这里不再建表；
状态标签由 corpus.effective_status 按人工核验结果与生效日期给出。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.database import Base

#: 政策状态标签（界面展示用）
STATUS_EFFECTIVE = "现行有效"
STATUS_REPEALED = "已废止"
STATUS_REVISED = "已修订"
STATUS_PENDING = "待核实"
STATUS_NOT_YET = "尚未生效"

ALL_STATUSES = (STATUS_EFFECTIVE, STATUS_REPEALED, STATUS_REVISED, STATUS_PENDING, STATUS_NOT_YET)

#: 可作为现行依据的状态：只有人工核验为现行、且在有效期内的政策
BASIS_STATUSES = (STATUS_EFFECTIVE,)


class PolicyQaLog(Base):
    """政策问答留痕：问、答、引用条款、是否无依据、人工反馈。

    这张表是「可审计」的落点：任何一个结论都能回溯到当时的条款与模型输出。
    """

    __tablename__ = "policy_qa_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, default="")
    citations_json = Column(Text, default="[]")
    scope = Column(String(32), default="current")
    status = Column(String(32), default="answered")   # answered / no_basis / needs_review / rejected
    generated_by = Column(String(32), default="")     # llm / extractive / none
    model = Column(String(128), default="")
    user_id = Column(Integer, nullable=True)
    feedback = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question": self.question,
            "answer": self.answer,
            "citations": self.citations_json,
            "scope": self.scope,
            "status": self.status,
            "generated_by": self.generated_by,
            "model": self.model,
            "feedback": self.feedback,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
