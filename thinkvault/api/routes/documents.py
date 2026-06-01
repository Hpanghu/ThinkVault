"""文档管理路由 — 上传 / 列表 / 删除"""

import traceback
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Query

from thinkvault.core.parser import DocumentParser
from thinkvault.core.chunker import TextChunker
from thinkvault.core.container import container
from thinkvault.core import document_store as doc_store
from thinkvault.utils.logger import logger

from thinkvault.api.schemas import UploadResponse, DocumentInfo, DeleteResponse

documents_router = APIRouter()

# 上传文件大小限制（100 MB）
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


@documents_router.post("/api/documents/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    knowledge_base: str = Query("default"),
):
    temp_path = None
    try:
        ext = Path(file.filename).suffix.lower()
        if ext not in DocumentParser.SUPPORTED_TYPES:
            return UploadResponse(
                file_name=file.filename, file_type=ext, chunk_count=0,
                status="error",
                error=f"不支持的文件格式: {ext}，目前支持 {DocumentParser.SUPPORTED_TYPES}",
            )

        project_root = Path(__file__).parent.parent.parent
        temp_dir = project_root / "temp_uploads"
        temp_dir.mkdir(exist_ok=True)
        safe_name = uuid.uuid4().hex + ext
        temp_path = temp_dir / safe_name
        content = await file.read()
        file_size = len(content)

        # P1-7 修复：拒绝超大文件上传，防止磁盘/内存耗尽
        if file_size > MAX_UPLOAD_BYTES:
            return UploadResponse(
                file_name=file.filename, file_type=ext, chunk_count=0,
                status="error",
                error=f"文件过大（{file_size / 1024 / 1024:.1f} MB），最大支持 {MAX_UPLOAD_BYTES / 1024 / 1024:.0f} MB",
            )

        temp_path.write_bytes(content)

        parsed = DocumentParser.parse(str(temp_path))
        if parsed.parse_error:
            return UploadResponse(
                file_name=file.filename, file_type=ext, chunk_count=0,
                status="error", error=parsed.parse_error,
            )

        chunker = TextChunker()
        chunks = chunker.chunk_document(parsed)
        if not chunks:
            return UploadResponse(
                file_name=file.filename, file_type=ext, chunk_count=0,
                status="error", error="文档内容为空",
            )

        texts = [c.text for c in chunks]
        embeddings = container.embedder.embed(texts)
        if embeddings is None:
            return UploadResponse(
                file_name=file.filename, file_type=ext, chunk_count=0,
                status="error", error="向量化失败",
            )

        container.vector_store.add_chunks(knowledge_base, chunks, embeddings)

        doc_id = doc_store.add_document(
            file_name=file.filename, file_type=ext.lstrip("."),
            file_size=file_size, knowledge_base=knowledge_base,
            chunk_count=len(chunks),
        )

        logger.info(f"文档已索引: {file.filename} ({len(chunks)} 块, KB={knowledge_base})")
        return UploadResponse(
            file_name=file.filename, file_type=ext, chunk_count=len(chunks),
            status="ok", doc_id=doc_id,
        )
    except Exception as e:
        logger.error(f"上传失败: {e}\n{traceback.format_exc()}")
        return UploadResponse(
            file_name=file.filename if file else "unknown", file_type="",
            chunk_count=0, status="error", error=str(e),
        )
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


@documents_router.get("/api/documents")
async def list_documents(knowledge_base: str = Query(None)):
    docs = doc_store.list_documents(knowledge_base=knowledge_base)
    return [DocumentInfo(**d) for d in docs]


@documents_router.delete("/api/documents/{doc_id}", response_model=DeleteResponse)
async def delete_document(doc_id: str):
    doc = doc_store.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
    kb = doc["knowledge_base"]
    file_name = doc["file_name"]
    try:
        collection = container.vector_store.get_or_create_collection(kb)
        # P3 修复：利用 ChromaDB where 过滤精确删除，避免全量加载 ID
        collection.delete(where={"source_file": file_name})
    except Exception as e:
        logger.warning(f"删除向量失败: {e}")
    doc_store.delete_document(doc_id)
    return DeleteResponse(status="ok", doc_id=doc_id, message=f"已删除: {file_name}")