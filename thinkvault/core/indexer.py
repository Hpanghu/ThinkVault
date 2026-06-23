"""文档索引统一入口：解析 → 分块 → 向量化 → 存储"""
from thinkvault.utils.logger import logger


def index_document(
    file_path: str,
    knowledge_base: str,
    chunk_size: int = 512,
    chunk_overlap: int = 128,
    doc_id: str | None = None,
) -> dict:
    """索引单个文档到知识库

    Returns:
        dict with keys: chunks_count, document_id, file_name, status, error
    """
    from thinkvault.core.parser import DocumentParser
    from thinkvault.core.chunker import TextChunker, ChunkConfig
    from thinkvault.core.container import container
    from thinkvault.core import document_store as doc_store

    file_name = file_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]

    try:
        # 1. 解析
        parsed = DocumentParser.parse(file_path)
        if parsed.parse_error:
            return {"chunks_count": 0, "document_id": None, "file_name": file_name, "status": "parse_error", "error": parsed.parse_error}

        if parsed.is_empty:
            return {"chunks_count": 0, "document_id": None, "file_name": file_name, "status": "empty", "error": "文档内容为空"}

        # 2. 分块
        config = ChunkConfig(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        chunker = TextChunker(config)
        chunks = chunker.chunk_document(parsed, doc_id=doc_id or "")
        if not chunks:
            return {"chunks_count": 0, "document_id": None, "file_name": file_name, "status": "no_chunks", "error": None}

        # 3. 向量化 + 存储
        texts = [c.text for c in chunks]
        embeddings = container.embedder.embed(texts)
        if embeddings is None:
            return {"chunks_count": 0, "document_id": None, "file_name": file_name, "status": "embed_failed", "error": "Embedding failed"}

        container.vector_store.add_chunks(knowledge_base, chunks, embeddings)

        # 4. 记录文档元数据
        preview_text = parsed.raw_text[:500] if parsed.raw_text else ""
        result_doc_id = doc_store.add_document(
            file_name=file_name,
            file_type=parsed.file_type,
            file_size=0,
            knowledge_base=knowledge_base,
            chunk_count=len(chunks),
            preview=preview_text,
            page_count=parsed.total_pages,
            file_path=file_path,
            doc_id=doc_id,
        )

        return {"chunks_count": len(chunks), "document_id": result_doc_id, "file_name": file_name, "status": "success", "error": None}

    except Exception as e:
        logger.error(f"索引文档失败 [{file_path}]: {e}", exc_info=True)
        return {"chunks_count": 0, "document_id": None, "file_name": file_name, "status": "error", "error": str(e)}
