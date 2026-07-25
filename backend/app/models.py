"""SQLAlchemy models: users, conversations, messages, files, api_settings"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    nickname = Column(String(64), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    conversations = relationship("Conversation", back_populates="user")


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(256), default="新对话")
    workflow_type = Column(String(32), default="chat", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", order_by="Message.id")


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    role = Column(String(16), nullable=False)  # user / assistant
    content = Column(Text, nullable=False)
    msg_type = Column(String(16), default="text")  # text / audio / file
    workflow_type = Column(String(32), default="chat", nullable=False, index=True)
    intent_type = Column(String(64), default="", index=True)
    metadata_json = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    conversation = relationship("Conversation", back_populates="messages")
    attachments = relationship("MessageAttachment", back_populates="message", cascade="all, delete-orphan")


class MessageAttachment(Base):
    __tablename__ = "message_attachments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, index=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    message = relationship("Message", back_populates="attachments")
    file = relationship("File")


class File(Base):
    __tablename__ = "files"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    filename = Column(String(256), nullable=False)
    filepath = Column(String(512), nullable=False)
    real_path = Column(String(1024), nullable=True)
    filesize = Column(Integer, default=0)
    size = Column(Integer, nullable=True)
    filetype = Column(String(64), default="")
    mime_type = Column(String(128), nullable=True)
    project_id = Column(String(128), nullable=True, index=True)
    task_id = Column(String(128), nullable=True, index=True)
    sha256 = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True, index=True)


class PPTMediaAsset(Base):
    __tablename__ = "ppt_media_assets"
    __table_args__ = (UniqueConstraint("owner_user_id", "sha256", name="uq_ppt_media_owner_sha"),)

    asset_id = Column(String(64), primary_key=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False, index=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source_type = Column(String(32), nullable=False, index=True)
    source_file_id = Column(Integer, ForeignKey("files.id"), nullable=True, index=True)
    mime_type = Column(String(128), nullable=False)
    width = Column(Integer, nullable=False, default=0)
    height = Column(Integer, nullable=False, default=0)
    sha256 = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="ready", index=True)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)


class PPTProjectMediaAsset(Base):
    __tablename__ = "ppt_project_media_assets"
    __table_args__ = (UniqueConstraint("project_id", "asset_id", name="uq_ppt_project_media_asset"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(64), nullable=False, index=True)
    asset_id = Column(String(64), ForeignKey("ppt_media_assets.asset_id"), nullable=False, index=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PPTGenerationRequest(Base):
    __tablename__ = "ppt_generation_requests"
    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_ppt_generation_user_request"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    request_id = Column(String(64), nullable=False)
    task_id = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="accepted", index=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=True)
    event_type = Column(String(16), nullable=True)
    response_json = Column(Text, default="")
    error_code = Column(String(64), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PPTIncrementalTask(Base):
    __tablename__ = "ppt_incremental_tasks"
    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_ppt_incremental_user_request"),
    )

    task_id = Column(String(64), primary_key=True)
    project_id = Column(String(64), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    request_id = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="accepted", index=True)
    sequence = Column(Integer, nullable=False, default=0)
    page_count = Column(Integer, nullable=False)
    outline_json = Column(Text, default="[]")
    completed_slides_json = Column(Text, default="[]")
    current_slide_json = Column(Text, default="")
    errors_json = Column(Text, default="[]")
    metrics_json = Column(Text, default="{}")
    final_file_json = Column(Text, default="")
    source_refs_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PPTIncrementalEvent(Base):
    __tablename__ = "ppt_incremental_events"
    __table_args__ = (
        UniqueConstraint("task_id", "sequence", name="uq_ppt_incremental_task_sequence"),
    )

    event_id = Column(String(64), primary_key=True)
    task_id = Column(String(64), ForeignKey("ppt_incremental_tasks.task_id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(64), nullable=False, index=True)
    payload_json = Column(Text, default="{}")
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)


class PPTEditorDocument(Base):
    __tablename__ = "ppt_editor_documents"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_ppt_editor_project_user"),
    )

    document_id = Column(String(64), primary_key=True)
    project_id = Column(String(64), nullable=False, index=True)
    base_task_id = Column(String(64), ForeignKey("ppt_incremental_tasks.task_id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    original_file_id = Column(Integer, ForeignKey("files.id"), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    document_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PPTEditorExport(Base):
    __tablename__ = "ppt_editor_exports"

    export_id = Column(String(64), primary_key=True)
    project_id = Column(String(64), nullable=False, index=True)
    base_task_id = Column(String(64), ForeignKey("ppt_incremental_tasks.task_id"), nullable=False, index=True)
    document_id = Column(String(64), ForeignKey("ppt_editor_documents.document_id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False, index=True)
    sha256 = Column(String(64), nullable=False)
    filesize = Column(Integer, nullable=False)
    report_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)


class PPTTemplate(Base):
    __tablename__ = "ppt_templates"

    template_id = Column(String(64), primary_key=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source_file_id = Column(Integer, ForeignKey("files.id"), nullable=False, index=True)
    title = Column(String(256), nullable=False, default="")
    status = Column(String(32), nullable=False, default="uploaded", index=True)
    sha256 = Column(String(64), nullable=False, index=True)
    slide_count = Column(Integer, nullable=False, default=0)
    canvas_width = Column(Integer, nullable=False, default=0)
    canvas_height = Column(Integer, nullable=False, default=0)
    analysis_json = Column(Text, default="{}")
    preview_manifest_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PPTTemplateFillPlan(Base):
    __tablename__ = "ppt_template_fill_plans"

    plan_id = Column(String(64), primary_key=True)
    template_id = Column(String(64), ForeignKey("ppt_templates.template_id"), nullable=False, index=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source_file_ids_json = Column(Text, default="[]")
    plan_json = Column(Text, nullable=False, default="{}")
    status = Column(String(32), nullable=False, default="draft", index=True)
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PPTTemplateFillTask(Base):
    __tablename__ = "ppt_template_fill_tasks"

    task_id = Column(String(64), primary_key=True)
    template_id = Column(String(64), ForeignKey("ppt_templates.template_id"), nullable=False, index=True)
    plan_id = Column(String(64), ForeignKey("ppt_template_fill_plans.plan_id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    route_type = Column(String(32), nullable=False, default="template_fill")
    source_file_id = Column(Integer, ForeignKey("files.id"), nullable=False, index=True)
    output_file_id = Column(Integer, ForeignKey("files.id"), nullable=True, index=True)
    status = Column(String(32), nullable=False, default="queued", index=True)
    options_json = Column(Text, default="{}")
    validation_json = Column(Text, default="{}")
    artifact_manifest_json = Column(Text, default="{}")
    error_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class PPTNativeEnhanceTask(Base):
    __tablename__ = "ppt_native_enhance_tasks"

    task_id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    route_type = Column(String(32), nullable=False, default="native_enhance")
    source_file_id = Column(Integer, ForeignKey("files.id"), nullable=False, index=True)
    source_sha256 = Column(String(64), nullable=False)
    output_file_id = Column(Integer, ForeignKey("files.id"), nullable=True, index=True)
    output_sha256 = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, default="queued", index=True)
    stage = Column(String(64), nullable=False, default="queued")
    options_json = Column(Text, default="{}")
    validation_json = Column(Text, default="{}")
    artifact_manifest_json = Column(Text, default="{}")
    error_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class PandaWikiSyncTask(Base):
    __tablename__ = "pandawiki_sync_tasks"
    task_id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False, index=True)
    status = Column(String(32), default="queued", index=True)
    progress = Column(Integer, default=0)
    stage = Column(String(128), default="")
    kb_id = Column(String(128), default="")
    nav_id = Column(String(128), default="")
    remote_key = Column(String(512), default="")
    remote_doc_id = Column(String(512), default="")
    remote_node_id = Column(String(128), default="")
    remote_release_id = Column(String(128), default="")
    error = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ApiSetting(Base):
    __tablename__ = "api_settings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(128), unique=True, nullable=False, index=True)
    value = Column(Text, default="")
    description = Column(String(256), default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DocumentTask(Base):
    __tablename__ = "document_tasks"
    task_id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=True, index=True)
    workflow_type = Column(String(32), default="document", nullable=False, index=True)
    title = Column(String(256), default="document.docx")
    status = Column(String(32), default="queued", index=True)
    progress = Column(Integer, default=0)
    doc_type = Column(String(64), default="")
    engine = Column(String(64), default="")
    template_id = Column(String(128), default="")
    file_id = Column(Integer, ForeignKey("files.id"), nullable=True)
    error = Column(Text, default="")
    user_input = Column(Text, default="")
    route_json = Column(Text, default="")
    content_schema_json = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FileParseTask(Base):
    __tablename__ = "file_parse_tasks"
    task_id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False, index=True)
    parsed_file_id = Column(Integer, ForeignKey("parsed_files.id"), nullable=True)
    status = Column(String(32), default="queued", index=True)
    progress = Column(Integer, default=0)
    stage = Column(String(128), default="")
    error = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ParsedFile(Base):
    __tablename__ = "parsed_files"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False, index=True)
    sha256 = Column(String(64), nullable=False, index=True)
    mime_type = Column(String(128), default="")
    title = Column(String(256), default="")
    markdown = Column(Text, default="")
    metadata_json = Column(Text, default="")
    page_count = Column(Integer, default=0)
    ocr_pages_json = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class ParsedFileChunk(Base):
    __tablename__ = "parsed_file_chunks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    parsed_file_id = Column(Integer, ForeignKey("parsed_files.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    chunk_index = Column(Integer, default=0)
    page_start = Column(Integer, default=0)
    page_end = Column(Integer, default=0)
    content = Column(Text, default="")
    summary = Column(Text, default="")
    token_estimate = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class PPTStructuredWorkspace(Base):
    """Structured PowerPoint workspace with explicit Master/Layout/Placeholder definitions"""
    __tablename__ = "ppt_structured_workspaces"
    
    workspace_id = Column(String(64), primary_key=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(256), nullable=False)
    source_type = Column(String(32), default="builtin", index=True)  # builtin / template_derived / user_created
    source_template_id = Column(String(64), nullable=True)
    status = Column(String(32), default="draft", index=True)  # draft / validated / active
    version = Column(Integer, default=1)
    canvas = Column(String(32), default="ppt169")  # ppt169 / ppt43 / a4
    theme_json = Column(Text, default="{}")  # colors, fonts
    master_manifest_json = Column(Text, default="[]")  # [{master_id, name, ...}]
    layout_manifest_json = Column(Text, default="[]")  # [{layout_id, master_id, kind, placeholders, ...}]
    placeholder_manifest_json = Column(Text, default="[]")  # [{ph_id, layout_id, type, idx, ...}]
    asset_manifest_json = Column(Text, default="[]")  # embedded images/icons
    validation_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# --- P3-B Guided Strategist: register GuidedProject on the shared metadata ---
from app.PPT_master.guided_models import GuidedProject  # noqa: F401

