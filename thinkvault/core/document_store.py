"""
SQLite 文档元数据存储 — 记录已索引文档的元信息
"""

import uuid
from datetime import datetime
from typing import Optional

from thinkvault.core.base_store import BaseStore
from thinkvault.utils.logger import logger

DOCUMENTS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        file_name TEXT NOT NULL,
        file_type TEXT NOT NULL,
        file_size INTEGER NOT NULL,
        knowledge_base TEXT NOT NULL DEFAULT 'default',
        chunk_count INTEGER NOT NULL DEFAULT 0,
        upload_time TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'indexed',
        preview TEXT,
        page_count INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_documents_kb ON documents(knowledge_base)
"""

# 增量迁移：为已有表添加新列（向后兼容）
_MIGRATIONS = [
    "ALTER TABLE documents ADD COLUMN preview TEXT",
    "ALTER TABLE documents ADD COLUMN page_count INTEGER",
    "ALTER TABLE documents ADD COLUMN tags TEXT DEFAULT ''",
    "ALTER TABLE documents ADD COLUMN file_path TEXT DEFAULT ''",
    "ALTER TABLE documents ADD COLUMN content_hash TEXT DEFAULT ''",
    "ALTER TABLE documents ADD COLUMN mtime REAL DEFAULT 0",
    "CREATE INDEX IF NOT EXISTS idx_documents_kb ON documents(knowledge_base)",
    "CREATE INDEX IF NOT EXISTS idx_documents_file_path ON documents(file_path)",
    "CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash)",
]


class _Store(BaseStore):
    _SCHEMA = DOCUMENTS_SCHEMA
    _MIGRATIONS = _MIGRATIONS


_instance = _Store()


def add_document(
    file_name: str,
    file_type: str,
    file_size: int,
    knowledge_base: str = "default",
    chunk_count: int = 0,
    preview: Optional[str] = None,
    page_count: Optional[int] = None,
    tags: str = "",
    file_path: str = "",
    content_hash: str = "",
    mtime: float = 0,
    doc_id: Optional[str] = None,
) -> str:
    """添加文档记录。

    Args:
        file_name: 文件名
        file_type: 文件类型（不含点号）
        file_size: 文件大小（字节）
        knowledge_base: 所属知识库
        chunk_count: 分块数量
        preview: 文档预览文本（解析后前500字符）
        page_count: 文档页数/段数
        tags: 文档标签
        file_path: 文件路径
        content_hash: 内容哈希
        mtime: 文件修改时间戳
        doc_id: 可选的文档ID（不传则自动生成）

    Returns:
        str: 文档 ID
    """
    if doc_id is None:
        doc_id = uuid.uuid4().hex[:16]  # 64-bit 熵值，百亿级碰撞概率可接受
    with _instance._get_store().connect() as conn:
        conn.execute(
            "INSERT INTO documents (id, file_name, file_type, file_size, knowledge_base, "
            "chunk_count, upload_time, status, preview, page_count, "
            "tags, file_path, content_hash, mtime) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_id, file_name, file_type, file_size, knowledge_base, chunk_count,
             datetime.now().isoformat(), "indexed", preview, page_count,
             tags, file_path, content_hash, mtime)
        )
        conn.commit()
    return doc_id


def list_documents(knowledge_base: Optional[str] = None, limit: Optional[int] = None, offset: int = 0) -> list[dict]:
    with _instance._get_store().connect() as conn:
        if knowledge_base:
            sql = "SELECT * FROM documents WHERE knowledge_base=? ORDER BY upload_time DESC"
            params: list = [knowledge_base]
        else:
            sql = "SELECT * FROM documents ORDER BY upload_time DESC"
            params = []
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def count_documents(knowledge_base: Optional[str] = None) -> int:
    """返回文档总数（可选按知识库过滤）。"""
    with _instance._get_store().connect() as conn:
        if knowledge_base:
            row = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE knowledge_base=?",
                (knowledge_base,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM documents").fetchone()
        return row[0] if row else 0


def get_document(doc_id: str) -> Optional[dict]:
    with _instance._get_store().connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        return dict(row) if row else None


def get_document_preview(doc_id: str) -> Optional[dict]:
    """获取文档预览信息。

    Returns:
        dict with keys: id, file_name, file_type, file_size, knowledge_base,
                        chunk_count, upload_time, status, preview, page_count
        如果文档不存在返回 None
    """
    doc = get_document(doc_id)
    return doc


def delete_document(doc_id: str) -> bool:
    with _instance._get_store().connect() as conn:
        cursor = conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        return deleted


def delete_documents_by_kb(knowledge_base: str) -> int:
    with _instance._get_store().connect() as conn:
        cursor = conn.execute("DELETE FROM documents WHERE knowledge_base=?", (knowledge_base,))
        count = cursor.rowcount
        conn.commit()
        return count


def update_tags(doc_id: str, tags: str) -> bool:
    """更新文档标签。"""
    with _instance._get_store().connect() as conn:
        cursor = conn.execute(
            "UPDATE documents SET tags=? WHERE id=?", (tags, doc_id)
        )
        updated = cursor.rowcount > 0
        conn.commit()
        return updated


def get_by_file_path(file_path: str) -> Optional[dict]:
    """按文件路径查询文档。"""
    with _instance._get_store().connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE file_path=?", (file_path,)).fetchone()
        return dict(row) if row else None


def get_by_content_hash(content_hash: str) -> list[dict]:
    """按内容哈希查询文档。"""
    with _instance._get_store().connect() as conn:
        rows = conn.execute(
            "SELECT * FROM documents WHERE content_hash=?", (content_hash,)
        ).fetchall()
        return [dict(r) for r in rows]
