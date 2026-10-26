"""政策库数据模型。

设计目标：把「政策」当有生命周期的对象管理，而不是当一段待切片的文本。

一个政策 = 元数据（文号、机关、生效/失效、状态、替代关系）+ 若干条款。
条款是解读与引用的最小单位：每条都能定位到原文页码与字符区间，并带校验值。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base

#: 政策状态（与原型的状态标签一致）
STATUS_EFFECTIVE = "现行有效"
STATUS_REPEALED = "已废止"
STATUS_REVISED = "已修订"
STATUS_PENDING = "待核实"
STATUS_NOT_YET = "尚未生效"

ALL_STATUSES = (STATUS_EFFECTIVE, STATUS_REPEALED, STATUS_REVISED, STATUS_PENDING, STATUS_NOT_YET)

#: 可作为现行依据的状态
BASIS_STATUSES = (STATUS_EFFECTIVE,)


class PolicyDocument(Base):
    """一件政策文件。"""

    __tablename__ = "policy_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # ---- 基本信息 ----
    title = Column(String(512), nullable=False, index=True)
    doc_no = Column(String(128), default="", index=True)          # 文号
    issuer = Column(String(256), default="")                      # 发文机关
    source_url = Column(String(1024), default="")                 # 原始来源链接
    region = Column(String(128), default="")                      # 地区
    target_audience = Column(String(256), default="")             # 适用对象
    theme = Column(String(256), default="")                       # 政策主题

    # ---- 生命周期 ----
    publish_date = Column(String(20), default="")                 # YYYY-MM-DD
    effective_date = Column(String(20), default="")
    expire_date = Column(String(20), default="")
    status = Column(String(16), default=STATUS_EFFECTIVE, index=True)
    supersedes = Column(String(512), default="")                  # 被本文件替代的旧文件
    superseded_by = Column(String(512), default="")               # 替代本文件的新文件
    revision_of = Column(String(512), default="")                 # 修订自哪一版
    version = Column(String(32), default="")
    review_note = Column(Text, default="")                        # 待核实说明 / 人工核实备注

    # ---- 原文与校验 ----
    file_name = Column(String(512), default="")
    file_path = Column(String(1024), default="")
    page_count = Column(Integer, default=0)
    clause_count = Column(Integer, default=0)
    char_count = Column(Integer, default=0)
    checksum = Column(String(64), default="")                     # 原文校验值（sha256 前 32 位）

    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    clauses = relationship(
        "PolicyClause", back_populates="policy", cascade="all, delete-orphan",
        order_by="PolicyClause.seq",
    )

    __table_args__ = (
        UniqueConstraint("doc_no", "checksum", name="uq_policy_docno_checksum"),
    )

    def to_dict(self, *, with_clauses: bool = False) -> dict:
        data = {
            "id": self.id,
            "title": self.title,
            "doc_no": self.doc_no,
            "issuer": self.issuer,
            "source_url": self.source_url,
            "region": self.region,
            "target_audience": self.target_audience,
            "theme": self.theme,
            "publish_date": self.publish_date,
            "effective_date": self.effective_date,
            "expire_date": self.expire_date,
            "status": self.status,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
            "revision_of": self.revision_of,
            "version": self.version,
            "review_note": self.review_note,
            "file_name": self.file_name,
            "page_count": self.page_count,
            "clause_count": self.clause_count,
            "char_count": self.char_count,
            "checksum": self.checksum,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if with_clauses:
            data["clauses"] = [c.to_dict() for c in self.clauses]
        return data


class PolicyClause(Base):
    """政策中的一条（或一款）。引用与解读的最小单位。"""

    __tablename__ = "policy_clauses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    policy_id = Column(Integer, ForeignKey("policy_documents.id", ondelete="CASCADE"),
                       nullable=False, index=True)

    seq = Column(Integer, default=0)                 # 全文顺序
    clause_no = Column(String(64), default="")       # 如「第六条」
    chapter = Column(String(128), default="")        # 所属章，如「第三章 申请与受理」
    heading = Column(String(256), default="")        # 条款首句摘要
    content = Column(Text, nullable=False)           # 条款原文
    page = Column(Integer, default=1)                # 起始页码
    char_start = Column(Integer, default=0)          # 在全文中的字符起点
    char_end = Column(Integer, default=0)
    checksum = Column(String(64), default="")        # 条款原文校验值
    search_text = Column(Text, default="")           # 归一化检索文本（去标点、小写）

    policy = relationship("PolicyDocument", back_populates="clauses")

    __table_args__ = (
        Index("ix_policy_clause_policy_seq", "policy_id", "seq"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "policy_id": self.policy_id,
            "seq": self.seq,
            "clause_no": self.clause_no,
            "chapter": self.chapter,
            "heading": self.heading,
            "content": self.content,
            "page": self.page,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "checksum": self.checksum,
        }


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
