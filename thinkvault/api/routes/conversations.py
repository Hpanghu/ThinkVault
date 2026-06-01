"""会话管理路由 — CRUD"""

from fastapi import APIRouter, HTTPException

from thinkvault.core import conversation_store as conv_store

from thinkvault.api.schemas import (
    ConversationCreate, ConversationInfo, MessageInfo,
)

conversations_router = APIRouter()


@conversations_router.get("/api/conversations")
async def list_conversations():
    return [ConversationInfo(**c) for c in conv_store.list_conversations()]


@conversations_router.post("/api/conversations")
async def create_conversation(req: ConversationCreate):
    return ConversationInfo(**conv_store.create_conversation(title=req.title))


@conversations_router.get("/api/conversations/{conv_id}")
async def get_conversation_detail(conv_id: str):
    conv = conv_store.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail=f"会话不存在: {conv_id}")
    conv["messages"] = conv_store.get_messages(conv_id)
    return ConversationInfo(**conv)


@conversations_router.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    if not conv_store.delete_conversation(conv_id):
        raise HTTPException(status_code=404, detail=f"会话不存在: {conv_id}")
    return {"status": "ok", "deleted": conv_id}


@conversations_router.patch("/api/conversations/{conv_id}")
async def rename_conversation(conv_id: str, req: ConversationCreate):
    if not conv_store.update_conversation(conv_id, title=req.title):
        raise HTTPException(status_code=404, detail=f"会话不存在: {conv_id}")
    return ConversationInfo(**conv_store.get_conversation(conv_id))


@conversations_router.get("/api/conversations/{conv_id}/messages")
async def get_conversation_messages(conv_id: str):
    conv = conv_store.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail=f"会话不存在: {conv_id}")
    return [MessageInfo(**m) for m in conv_store.get_messages(conv_id)]