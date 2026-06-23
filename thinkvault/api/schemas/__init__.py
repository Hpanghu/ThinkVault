"""API 数据模型 — V2.0"""

import re
from pydantic import BaseModel, Field
from typing import Any, Optional


class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        max_length=10000,
        description="用户消息内容，最大 10000 字符",
    )
    knowledge_base: str = Field(
        default="default",
        max_length=50,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
        description="知识库名称：小写字母/数字开头，仅允许小写字母、数字、连字符和下划线",
    )
    history: list[dict] = Field(default_factory=list)  # [{"role":"user","content":"..."}, ...]
    system_prompt: str = ""
    conversation_id: Optional[str] = None
    stream: bool = False
    role_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[str] = []
    stats: Optional[dict] = None
    conversation_id: Optional[str] = None
    mode: str = "chat"  # "chat" | "retrieval_only" | "no_result" — 标记响应模式


class UploadResponse(BaseModel):
    file_name: str
    file_type: str
    chunk_count: int
    status: str
    error: Optional[str] = None
    doc_id: Optional[str] = None


class DocumentInfo(BaseModel):
    id: str
    file_name: str
    file_type: str
    file_size: int
    knowledge_base: str
    chunk_count: int
    upload_time: str
    status: str
    preview: Optional[str] = None
    page_count: Optional[int] = None


class DocumentPreviewResponse(BaseModel):
    """文档预览响应"""
    id: str
    file_name: str
    file_type: str
    file_size: int
    knowledge_base: str
    chunk_count: int
    upload_time: str
    status: str
    preview: Optional[str] = None
    page_count: Optional[int] = None
    full_text: Optional[str] = None


class DocumentScanRequest(BaseModel):
    """文件夹扫描请求"""
    directory: str
    knowledge_base: str = "default"
    recursive: bool = True


class DocumentScanResponse(BaseModel):
    """文件夹扫描响应"""
    directory: str = ""
    scanned: int = 0
    new: int = 0
    skipped: int = 0
    unsupported: int = 0
    errors: list[str] = []
    details: list[dict] = []


class KnowledgeBaseInfo(BaseModel):
    name: str
    chunk_count: int
    document_count: int = 0


class KnowledgeBaseCreate(BaseModel):
    name: str


class ModelLoadRequest(BaseModel):
    model_path: str
    model_name: str = ""
    n_ctx: int = 2048
    api_key: str = ""


class ModelInfo(BaseModel):
    loaded: bool
    model_path: str = ""
    model_name: str = ""
    backend: str = "openai"


class HardwareInfo(BaseModel):
    cpu_count: int
    total_ram_gb: float
    available_ram_gb: float
    gpu_name: str
    vram_gb: float
    has_cuda: bool
    recommended_tier: str
    recommended_spec: dict


class DeleteResponse(BaseModel):
    status: str
    doc_id: str
    message: str = ""


# ============================== V2.0 对话管理 ==============================

class ConversationCreate(BaseModel):
    title: str = Field(default="New Chat", max_length=200, description="会话标题，最大 200 字符")
    role_id: Optional[str] = None


class ConversationInfo(BaseModel):
    id: str
    title: str
    role_id: Optional[str] = None
    created_at: str
    message_count: int = 0
    messages: list[dict] = []


class MessageInfo(BaseModel):
    id: str
    conv_id: str
    role: str
    content: str
    created_at: str


# ── Response Models ──────────────────────────────────────────────

class DocumentListResponse(BaseModel):
    documents: list[DocumentInfo]
    total: int
    limit: int
    offset: int


class KnowledgeBaseListResponse(BaseModel):
    knowledge_bases: list[KnowledgeBaseInfo]


class ConversationItem(BaseModel):
    id: str
    title: str
    created_at: str = ""
    updated_at: str = ""
    message_count: int = 0


class ConversationListResponse(BaseModel):
    conversations: list[ConversationItem]
    total: int
    limit: int
    offset: int


class MessageItem(BaseModel):
    id: str
    conv_id: str = ""
    role: str
    content: str
    created_at: str = ""


class ConversationDetail(BaseModel):
    id: str
    title: str
    role_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    message_count: int = 0
    messages: list[MessageItem] = []


class TaskResponse(BaseModel):
    task_id: str
    status: str
    description: str = ""
    progress: float = 0.0
    result: Any = None


class ServiceStatus(BaseModel):
    services: dict = {}
    total: int = 0
    running: int = 0


class ModelListItem(BaseModel):
    id: str
    name: str
    source: str = "local"
    size_mb: float = 0.0
    path: str = ""


class ModelListResponse(BaseModel):
    models: list[ModelListItem]
    count: int = 0
