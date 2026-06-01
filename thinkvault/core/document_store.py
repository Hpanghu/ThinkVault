"""
SQLite 文档元数据存储 — 记录已索引文档的元信息
"""

import uuid
from datetime import datetime
from typing import Optional

from thinkvault.core.db import SqliteStore

DOCUMENTS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        file_name TEXT NOT NULL,
        file_type TEXT NOT NULL,
        file_size INTEGER NOT NULL,
        knowledge_base TEXT NOT NULL DEFAULT 'default',
        chunk_count INTEGER NOT NULL DEFAULT 0,
        upload_time TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'indexed'
    )
"""

_store = None  # 惰性初始化，避免 import 时立即连接数据库


def _get_store() -> SqliteStore:
    """惰性获取 SQLite 存储实例（线程安全）"""
    global _store
    if _store is None:
        _store = SqliteStore("documents.db")
        _store.init_schema(DOCUMENTS_SCHEMA)
    return _store


def add_document(file_name: str, file_type: str, file_size: int,
                 knowledge_base: str = "default", chunk_count: int = 0) -> str:
    doc_id = uuid.uuid4().hex[:16]  # 64-bit 熵值，百亿级碰撞概率可接受
    with _get_store().connect() as conn:
        conn.execute(
            "INSERT INTO documents (id, file_name, file_type, file_size, knowledge_base, chunk_count, upload_time, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_id, file_name, file_type, file_size, knowledge_base, chunk_count,
             datetime.now().isoformat(), "indexed")
        )
        conn.commit()
    return doc_id


def list_documents(knowledge_base: Optional[str] = None) -> list[dict]:
    with _get_store().connect() as conn:
        if knowledge_base:
            rows = conn.execute(
                "SELECT * FROM documents WHERE knowledge_base=? ORDER BY upload_time DESC",
                (knowledge_base,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM documents ORDER BY upload_time DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_document(doc_id: str) -> Optional[dict]:
    with _get_store().connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        return dict(row) if row else None


def delete_document(doc_id: str) -> bool:
    with _get_store().connect() as conn:
        cursor = conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        return deleted


def delete_documents_by_kb(knowledge_base: str) -> int:
    with _get_store().connect() as conn:
        cursor = conn.execute("DELETE FROM documents WHERE knowledge_base=?", (knowledge_base,))
        count = cursor.rowcount
        conn.commit()
        return count
