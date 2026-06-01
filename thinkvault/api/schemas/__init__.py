"""API 数据模型 — V2.0"""

from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    message: str
    knowledge_base: str = "default"
    history: list[dict] = []  # [{"role":"user","content":"..."}, ...]
    system_prompt: str = (
        "用中文回答用户的问题。仅基于提供的文档内容回答，"
        "如果文档中没有相关信息请如实说明。"
    )
    conversation_id: Optional[str] = None
    stream: bool = False


class ChatResponse(BaseModel):
    answer: str
    sources: list[str] = []
    stats: Optional[dict] = None
    conversation_id: Optional[str] = None
    mode: str = "chat"  # "chat" | "retrieval_only" — 标记响应模式


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


class KnowledgeBaseInfo(BaseModel):
    name: str
    chunk_count: int


class ModelLoadRequest(BaseModel):
    model_path: str
    n_ctx: int = 2048


class ModelInfo(BaseModel):
    loaded: bool
    model_path: str = ""


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
    title: str = "New Chat"


class ConversationInfo(BaseModel):
    id: str
    title: str
    created_at: str
    message_count: int = 0
    messages: list[dict] = []


class MessageInfo(BaseModel):
    id: str
    conv_id: str
    role: str
    content: str
    created_at: str
