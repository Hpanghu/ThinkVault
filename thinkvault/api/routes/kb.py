"""知识库管理路由"""

from fastapi import APIRouter

from thinkvault.core.container import container
from thinkvault.core import document_store as doc_store
from thinkvault.utils.logger import logger

from thinkvault.api.schemas import KnowledgeBaseInfo

kb_router = APIRouter()


@kb_router.get("/api/knowledge-bases")
async def list_knowledge_bases():
    kbs = container.vector_store.list_knowledge_bases()
    return [KnowledgeBaseInfo(name=kb, chunk_count=container.vector_store.get_chunk_count(kb)) for kb in kbs]


@kb_router.delete("/api/knowledge-bases/{name}")
async def delete_knowledge_base(name: str):
    container.vector_store.delete_knowledge_base(name)
    doc_store.delete_documents_by_kb(name)
    # 删除知识库时同步清理 retriever 缓存，避免重建同名 KB 时使用过期缓存
    container.retriever.invalidate_cache(name)
    return {"status": "ok"}