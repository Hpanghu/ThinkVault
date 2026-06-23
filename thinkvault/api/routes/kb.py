"""知识库管理路由"""

import asyncio
import re

from fastapi import APIRouter, HTTPException

from thinkvault.core.container import container
from thinkvault.core import document_store as doc_store
from thinkvault.core import file_change_store
from thinkvault.core import doc_summary_store
from thinkvault.core import watched_dir_store
from thinkvault.utils.logger import logger

from thinkvault.api.schemas import KnowledgeBaseInfo, KnowledgeBaseCreate, KnowledgeBaseListResponse

kb_router = APIRouter()

# 合法知识库名规则：小写字母/数字/连字符，3-50 字符
_KB_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{2,49}$')


@kb_router.get("/api/knowledge-bases", response_model=KnowledgeBaseListResponse)
async def list_knowledge_bases():
    result = await asyncio.to_thread(_list_knowledge_bases_sync)
    return {"knowledge_bases": result}


def _list_knowledge_bases_sync() -> list:
    """同步执行 KB 列表查询（含 N+1 循环），由 to_thread 调用避免阻塞事件循环"""
    kbs = container.vector_store.list_knowledge_bases()
    result = []
    for kb in kbs:
        chunk_count = container.vector_store.get_chunk_count(kb)
        docs = doc_store.list_documents(knowledge_base=kb)
        result.append(KnowledgeBaseInfo(name=kb, chunk_count=chunk_count, document_count=len(docs)))
    return result


@kb_router.post("/api/knowledge-bases", status_code=201)
async def create_knowledge_base(req: KnowledgeBaseCreate):
    """创建新知识库（本质上调用 ChromaDB get_or_create_collection）"""
    name = req.name.strip().lower()
    if not _KB_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="知识库名称仅允许小写字母、数字、连字符和下划线，长度 3-50，须以字母或数字开头",
        )
    existing = container.vector_store.list_knowledge_bases()
    if name in existing:
        raise HTTPException(status_code=409, detail=f"知识库 '{name}' 已存在")
    try:
        container.vector_store.get_or_create_collection(name)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=f"向量存储不可用，无法创建知识库: {e}")
    logger.info("知识库创建成功: %s", name)
    return KnowledgeBaseInfo(name=name, chunk_count=0)


@kb_router.delete("/api/knowledge-bases/{name}")
async def delete_knowledge_base(name: str):
    """删除知识库及所有关联数据"""
    if name not in container.vector_store.list_knowledge_bases():
        raise HTTPException(status_code=404, detail=f"知识库 '{name}' 不存在")

    stats = {}

    # 1. 删除向量存储
    try:
        container.vector_store.delete_knowledge_base(name)
        stats["vector_store"] = "deleted"
    except Exception as e:
        stats["vector_store"] = f"error: {e}"

    # 2. 删除文件变更记录
    try:
        count = file_change_store.delete_by_knowledge_base(name)
        stats["file_changes_deleted"] = count
    except Exception as e:
        stats["file_changes"] = f"error: {e}"

    # 3. 删除文档摘要
    try:
        count = doc_summary_store.delete_by_knowledge_base(name)
        stats["doc_summaries_deleted"] = count
    except Exception as e:
        stats["doc_summaries"] = f"error: {e}"

    # 4. 删除监听目录
    try:
        count = watched_dir_store.delete_by_knowledge_base(name)
        stats["watched_dirs_deleted"] = count
    except Exception as e:
        stats["watched_dirs"] = f"error: {e}"

    # 5. 删除文档记录
    try:
        count = doc_store.delete_documents_by_kb(name)
        stats["documents_deleted"] = count
    except Exception as e:
        stats["documents"] = f"error: {e}"

    # 6. 清理 retriever 缓存
    try:
        container.retriever.invalidate_cache(name)
        stats["retriever_cache"] = "invalidated"
    except Exception as e:
        stats["retriever_cache"] = f"error: {e}"

    logger.info("知识库删除完成: %s, 统计: %s", name, stats)
    return {"status": "ok", "stats": stats}
