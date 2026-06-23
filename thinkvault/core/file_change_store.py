"""
文件变更记录存储 — 跟踪文件系统变更与索引状态
"""

from datetime import datetime
from typing import Optional

from thinkvault.core.base_store import BaseStore
from thinkvault.utils.logger import logger

FILE_CHANGES_SCHEMA = """
    CREATE TABLE IF NOT EXISTS file_changes (
        file_path TEXT PRIMARY KEY,
        file_name TEXT NOT NULL,
        knowledge_base TEXT NOT NULL,
        file_size INTEGER NOT NULL,
        mtime REAL NOT NULL,
        content_hash TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        doc_id TEXT,
        chunk_count INTEGER NOT NULL DEFAULT 0,
        indexed_at TEXT,
        error_message TEXT,
        UNIQUE(file_path)
    );
    CREATE INDEX IF NOT EXISTS idx_file_changes_kb ON file_changes(knowledge_base);
    CREATE INDEX IF NOT EXISTS idx_file_changes_status ON file_changes(status)
"""

_MIGRATIONS: list[str] = []


class _Store(BaseStore):
    _SCHEMA = FILE_CHANGES_SCHEMA
    _MIGRATIONS = _MIGRATIONS


_instance = _Store()


def upsert(
    file_path: str,
    file_name: str,
    knowledge_base: str,
    file_size: int,
    mtime: float,
    content_hash: str,
    status: str = "pending",
    doc_id: Optional[str] = None,
    chunk_count: int = 0,
    error_message: Optional[str] = None,
) -> dict:
    """幂等写入文件变更记录。"""
    now = datetime.now().isoformat()
    with _instance._get_store().connect() as conn:
        conn.execute(
            "INSERT INTO file_changes (file_path, file_name, knowledge_base, file_size, "
            "mtime, content_hash, status, doc_id, chunk_count, indexed_at, error_message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(file_path) DO UPDATE SET "
            "file_name=excluded.file_name, knowledge_base=excluded.knowledge_base, "
            "file_size=excluded.file_size, mtime=excluded.mtime, "
            "content_hash=excluded.content_hash, status=excluded.status, "
            "doc_id=excluded.doc_id, chunk_count=excluded.chunk_count, "
            "indexed_at=excluded.indexed_at, error_message=excluded.error_message",
            (file_path, file_name, knowledge_base, file_size, mtime, content_hash,
             status, doc_id, chunk_count, now, error_message),
        )
        conn.commit()
    return get(file_path)


def get_by_path(file_path: str) -> Optional[dict]:
    """按路径查询文件变更记录。"""
    with _instance._get_store().connect() as conn:
        row = conn.execute("SELECT * FROM file_changes WHERE file_path=?", (file_path,)).fetchone()
        return dict(row) if row else None


def get_by_knowledge_base(knowledge_base: str) -> list[dict]:
    """按知识库查询文件变更记录。"""
    with _instance._get_store().connect() as conn:
        rows = conn.execute(
            "SELECT * FROM file_changes WHERE knowledge_base=? ORDER BY file_path",
            (knowledge_base,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_by_status(knowledge_base: str, status: str) -> list[dict]:
    """按状态查询文件变更记录。"""
    with _instance._get_store().connect() as conn:
        rows = conn.execute(
            "SELECT * FROM file_changes WHERE knowledge_base=? AND status=? ORDER BY file_path",
            (knowledge_base, status),
        ).fetchall()
        return [dict(r) for r in rows]


def update_status(
    file_path: str,
    status: str,
    chunk_count: Optional[int] = None,
    doc_id: Optional[str] = None,
    error_message: Optional[str] = None,
) -> bool:
    """更新文件变更记录的状态。"""
    now = datetime.now().isoformat()
    with _instance._get_store().connect() as conn:
        sets = ["status=?", "indexed_at=?"]
        params: list = [status, now]
        if chunk_count is not None:
            sets.append("chunk_count=?")
            params.append(chunk_count)
        if doc_id is not None:
            sets.append("doc_id=?")
            params.append(doc_id)
        if error_message is not None:
            sets.append("error_message=?")
            params.append(error_message)
        params.append(file_path)
        cursor = conn.execute(
            f"UPDATE file_changes SET {', '.join(sets)} WHERE file_path=?", params
        )
        updated = cursor.rowcount > 0
        conn.commit()
        return updated


def delete_by_knowledge_base(knowledge_base: str) -> int:
    """按知识库删除文件变更记录。"""
    with _instance._get_store().connect() as conn:
        cursor = conn.execute("DELETE FROM file_changes WHERE knowledge_base=?", (knowledge_base,))
        count = cursor.rowcount
        conn.commit()
        return count


def get(file_path: str) -> Optional[dict]:
    """获取文件变更记录。"""
    return get_by_path(file_path)


def get_by_kb(knowledge_base: str, status: Optional[str] = None) -> list[dict]:
    """按知识库查询文件变更记录，可按状态过滤。"""
    with _instance._get_store().connect() as conn:
        if status is not None:
            rows = conn.execute(
                "SELECT * FROM file_changes WHERE knowledge_base=? AND status=? ORDER BY file_path",
                (knowledge_base, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM file_changes WHERE knowledge_base=? ORDER BY file_path",
                (knowledge_base,),
            ).fetchall()
        return [dict(r) for r in rows]


def delete(file_path: str) -> bool:
    """删除文件变更记录。"""
    with _instance._get_store().connect() as conn:
        cursor = conn.execute("DELETE FROM file_changes WHERE file_path=?", (file_path,))
        deleted = cursor.rowcount > 0
        conn.commit()
        return deleted


def get_pending(knowledge_base: str) -> list[dict]:
    """获取待处理（pending 或 error）的文件变更记录。"""
    with _instance._get_store().connect() as conn:
        rows = conn.execute(
            "SELECT * FROM file_changes WHERE knowledge_base=? AND status IN ('pending', 'error') ORDER BY file_path",
            (knowledge_base,),
        ).fetchall()
        return [dict(r) for r in rows]


def count_by_kb(knowledge_base: str) -> int:
    """统计知识库下的文件数量。"""
    with _instance._get_store().connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM file_changes WHERE knowledge_base=?",
            (knowledge_base,),
        ).fetchone()
        return row["cnt"] if row else 0
