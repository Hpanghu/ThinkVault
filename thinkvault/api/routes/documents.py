"""文档管理路由 — 上传 / 列表 / 删除 / 预览 / 扫描"""

import asyncio
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import JSONResponse

from thinkvault.core.parser import DocumentParser
from thinkvault.core.indexer import index_document
from thinkvault.core.container import container
from thinkvault.core import document_store as doc_store
from thinkvault.core.scanner import scan_directory
from thinkvault.utils.logger import logger

from thinkvault.api.schemas import (
    UploadResponse, DocumentInfo, DeleteResponse,
    DocumentScanRequest, DocumentScanResponse, DocumentPreviewResponse,
    DocumentListResponse,
)

documents_router = APIRouter()

# 上传文件大小限制（100 MB）
MAX_UPLOAD_BYTES = 100 * 1024 * 1024

# 上传文件名最大长度
MAX_FILENAME_LENGTH = 255


@documents_router.post("/api/documents/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    knowledge_base: str = Query("default"),
):
    temp_path = None
    try:
        # 文件名长度校验
        if file.filename and len(file.filename) > MAX_FILENAME_LENGTH:
            return UploadResponse(
                file_name=file.filename[:MAX_FILENAME_LENGTH], file_type="", chunk_count=0,
                status="error",
                error=f"文件名过长（{len(file.filename)} 字符），最大支持 {MAX_FILENAME_LENGTH} 字符",
            )

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

        # 流式写入，边读边检查大小限制，避免大文件撑爆内存
        size = 0
        CHUNK_SIZE = 1024 * 64  # 64KB
        with open(temp_path, "wb") as f:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    f.close()
                    temp_path.unlink(missing_ok=True)
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"文件过大（{size / 1024 / 1024:.1f} MB），最大支持 {MAX_UPLOAD_BYTES / 1024 / 1024:.0f} MB"},
                    )
                f.write(chunk)

        # 预生成 doc_id，用于关联 chunk metadata → 精确删除
        doc_id = uuid.uuid4().hex[:16]

        result = await asyncio.to_thread(
            index_document,
            str(temp_path),
            knowledge_base,
            doc_id=doc_id,
        )

        if result["status"] != "success":
            error_msg = result.get("error") or {
                "parse_error": "文档解析失败",
                "empty": "文档内容为空",
                "no_chunks": "分块结果为空",
                "embed_failed": "向量化失败",
            }.get(result["status"], "索引失败")
            return UploadResponse(
                file_name=file.filename, file_type=ext, chunk_count=0,
                status="error", error=error_msg,
            )

        logger.info(f"文档已索引: {file.filename} ({result['chunks_count']} 块, KB={knowledge_base})")
        return UploadResponse(
            file_name=file.filename, file_type=ext, chunk_count=result["chunks_count"],
            status="ok", doc_id=doc_id,
        )
    except Exception as e:
        logger.error(f"文件上传失败: {e}", exc_info=True)
        return UploadResponse(
            file_name=file.filename if file else "unknown", file_type="",
            chunk_count=0, status="error", error="文件上传失败，请稍后重试",
        )
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


@documents_router.get("/api/documents", response_model=DocumentListResponse)
async def list_documents(
    knowledge_base: str = Query(None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    total = await asyncio.to_thread(doc_store.count_documents, knowledge_base=knowledge_base)
    docs = await asyncio.to_thread(doc_store.list_documents, knowledge_base=knowledge_base, limit=limit, offset=offset)
    return {
        "documents": [DocumentInfo(**d) for d in docs],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@documents_router.get("/api/documents/{doc_id}/preview", response_model=DocumentPreviewResponse)
async def get_document_preview(doc_id: str):
    """获取文档预览：包含文件元数据 + 解析文本前2000字符 + 页数"""
    doc = await asyncio.to_thread(doc_store.get_document_preview, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")

    # 构建预览文本：优先用存储的 preview，截取前2000字符
    preview_text = doc.get("preview") or ""
    full_text = preview_text[:2000] if preview_text else None

    return DocumentPreviewResponse(
        id=doc["id"],
        file_name=doc["file_name"],
        file_type=doc["file_type"],
        file_size=doc["file_size"],
        knowledge_base=doc["knowledge_base"],
        chunk_count=doc["chunk_count"],
        upload_time=doc["upload_time"],
        status=doc["status"],
        preview=doc.get("preview"),
        page_count=doc.get("page_count"),
        full_text=full_text,
    )


@documents_router.delete("/api/documents/{doc_id}", response_model=DeleteResponse)
async def delete_document(doc_id: str):
    doc = await asyncio.to_thread(doc_store.get_document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
    kb = doc["knowledge_base"]
    file_name = doc["file_name"]
    try:
        collection = container.vector_store.get_or_create_collection(kb)
        # 使用 doc_id 精确删除，避免同名文件误删其他文档的向量数据
        collection.delete(where={"doc_id": doc_id})
    except Exception as e:
        logger.warning(f"删除向量失败: {e}")
    await asyncio.to_thread(doc_store.delete_document, doc_id)
    return DeleteResponse(status="ok", doc_id=doc_id, message=f"已删除: {file_name}")


@documents_router.post("/api/documents/scan", response_model=DocumentScanResponse)
async def scan_directory_endpoint(req: DocumentScanRequest):
    """扫描指定目录，自动索引所有新文件。

    已索引的文件（按文件名+大小匹配）会自动跳过。
    路径安全通过 THINKVAULT_SCAN_DIRS 环境变量白名单控制。
    """
    result = await asyncio.to_thread(
        scan_directory,
        directory_path=req.directory,
        knowledge_base=req.knowledge_base,
        recursive=req.recursive,
    )
    return DocumentScanResponse(**result)
