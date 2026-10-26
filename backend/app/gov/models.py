from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey
from app.database import Base


class GovDocument(Base):
    __tablename__ = "gov_documents"
    id = Column(String(32), primary_key=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="draft", index=True)
    version = Column(Integer, nullable=False, default=1)
    payload_json = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class GovDocumentMaterial(Base):
    __tablename__ = "gov_document_materials"
    document_id = Column(String(32), ForeignKey("gov_documents.id"), primary_key=True)
    file_id = Column(Integer, ForeignKey("files.id"), primary_key=True)


class GovReviewRecord(Base):
    __tablename__ = "gov_review_records"
    id = Column(String(32), primary_key=True)
    document_id = Column(String(32), ForeignKey("gov_documents.id"), nullable=False, index=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String(32), nullable=False)
    note = Column(Text, nullable=False, default="")
    tone = Column(String(16), nullable=False, default="neutral")
    at = Column(DateTime, nullable=False, default=datetime.utcnow)
