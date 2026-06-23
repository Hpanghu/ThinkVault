"""会话管理路由 — CRUD"""

import asyncio

from fastapi import APIRouter, HTTPException, Query

from thinkvault.core import conversation_store as conv_store

from thinkvault.api.schemas import (
    ConversationCreate, ConversationInfo,
    ConversationListResponse, ConversationItem,
    ConversationDetail, MessageItem,
)

conversations_router = APIRouter()


@conversations_router.get("/api/conversations", response_model=ConversationListResponse)
async def list_conversations(
    limit: int = Query(30, ge=1, le=100, description="返回条数上限"),
    offset: int = Query(0, ge=0, description="跳过条数"),
):
    """分页获取会话列表，按 updated_at DESC 排序"""
    convs = await asyncio.to_thread(conv_store.list_conversations, limit=limit, offset=offset)
    total = await asyncio.to_thread(conv_store.count_conversations)
    return {
        "conversations": [ConversationItem(**c) for c in convs],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@conversations_router.post("/api/conversations")
async def create_conversation(req: ConversationCreate):
    from thinkvault.config import get_default_role_id
    role_id = req.role_id or get_default_role_id()
    return ConversationInfo(**await asyncio.to_thread(conv_store.create_conversation, title=req.title, role_id=role_id))


@conversations_router.delete("/api/conversations")
async def delete_all_conversations():
    """删除所有会话及其消息（必须注册在 /{conv_id} 路由之前，避免路径参数拦截）"""
    count = await asyncio.to_thread(conv_store.delete_all_conversations)
    return {"status": "ok", "deleted_count": count}


@conversations_router.get("/api/conversations/{conv_id}", response_model=ConversationDetail)
async def get_conversation_detail(conv_id: str):
    conv = await asyncio.to_thread(conv_store.get_conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail=f"会话不存在: {conv_id}")
    messages = await asyncio.to_thread(conv_store.get_messages, conv_id)
    return ConversationDetail(
        id=conv["id"],
        title=conv["title"],
        role_id=conv.get("role_id", ""),
        created_at=conv.get("created_at", ""),
        updated_at=conv.get("updated_at", ""),
        message_count=conv.get("message_count", 0),
        messages=[MessageItem(**m) for m in messages],
    )


@conversations_router.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    if not await asyncio.to_thread(conv_store.delete_conversation, conv_id):
        raise HTTPException(status_code=404, detail=f"会话不存在: {conv_id}")
    return {"status": "ok", "deleted": conv_id}


@conversations_router.patch("/api/conversations/{conv_id}")
async def rename_conversation(conv_id: str, req: ConversationCreate):
    if not await asyncio.to_thread(conv_store.update_conversation, conv_id, title=req.title):
        raise HTTPException(status_code=404, detail=f"会话不存在: {conv_id}")
    return ConversationInfo(**await asyncio.to_thread(conv_store.get_conversation, conv_id))


@conversations_router.get("/api/conversations/{conv_id}/messages")
async def get_conversation_messages(conv_id: str):
    conv = await asyncio.to_thread(conv_store.get_conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail=f"会话不存在: {conv_id}")
    return [MessageItem(**m) for m in await asyncio.to_thread(conv_store.get_messages, conv_id)]