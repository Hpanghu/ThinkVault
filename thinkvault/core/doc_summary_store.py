"""
文档摘要存储 — 管理文档级别的摘要信息 + 摘要嵌入向量
"""

import json
import uuid
from datetime import datetime
from typing import Optional

from thinkvault.core.base_store import BaseStore
from thinkvault.utils.logger import logger

DOC_SUMMARIES_SCHEMA = """
    CREATE TABLE IF NOT EXISTS doc_summaries (
        id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        knowledge_base TEXT NOT NULL,
        summary TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_doc_summaries_kb ON doc_summaries(knowledge_base);
    CREATE INDEX IF NOT EXISTS idx_doc_summaries_status ON doc_summaries(status)
"""

_MIGRATIONS: list[str] = [
    # v2: 添加摘要嵌入列（JSON 编码的 float 列表），用于分层检索时预计算匹配
    "ALTER TABLE doc_summaries ADD COLUMN summary_embedding TEXT",
]


class _Store(BaseStore):
    _SCHEMA = DOC_SUMMARIES_SCHEMA
    _MIGRATIONS = _MIGRATIONS


_instance = _Store()


def add(
    doc_id: str,
    knowledge_base: str,
    summary: str,
    status: str = "pending",
) -> str:
    """添加文档摘要记录，返回 id。"""
    item_id = uuid.uuid4().hex
    now = datetime.now().isoformat()
    with _instance._get_store().connect() as conn:
        conn.execute(
            "INSERT INTO doc_summaries (id, doc_id, knowledge_base, summary, status, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (item_id, doc_id, knowledge_base, summary, status, now, now),
        )
        conn.commit()
    return item_id


def get(id: str) -> Optional[dict]:
    """获取文档摘要。"""
    with _instance._get_store().connect() as conn:
        row = conn.execute("SELECT * FROM doc_summaries WHERE id=?", (id,)).fetchone()
        return dict(row) if row else None


def get_by_doc_id(doc_id: str) -> Optional[dict]:
    """按文档 ID 获取摘要。"""
    with _instance._get_store().connect() as conn:
        row = conn.execute("SELECT * FROM doc_summaries WHERE doc_id=?", (doc_id,)).fetchone()
        return dict(row) if row else None


def get_by_knowledge_base(knowledge_base: str) -> list[dict]:
    """按知识库查询摘要。"""
    with _instance._get_store().connect() as conn:
        rows = conn.execute(
            "SELECT * FROM doc_summaries WHERE knowledge_base=? ORDER BY created_at DESC",
            (knowledge_base,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_by_status(knowledge_base: str, status: str) -> list[dict]:
    """按状态查询摘要。"""
    with _instance._get_store().connect() as conn:
        rows = conn.execute(
            "SELECT * FROM doc_summaries WHERE knowledge_base=? AND status=? ORDER BY created_at DESC",
            (knowledge_base, status),
        ).fetchall()
        return [dict(r) for r in rows]


def update_summary(id: str, summary: str, status: str = "generated") -> bool:
    """更新摘要内容和状态。"""
    now = datetime.now().isoformat()
    with _instance._get_store().connect() as conn:
        cursor = conn.execute(
            "UPDATE doc_summaries SET summary=?, status=?, updated_at=? WHERE id=?",
            (summary, status, now, id),
        )
        updated = cursor.rowcount > 0
        conn.commit()
        return updated


def update_embedding(id: str, embedding: list[float]) -> bool:
    """更新摘要嵌入向量（JSON 编码存储）"""
    now = datetime.now().isoformat()
    with _instance._get_store().connect() as conn:
        cursor = conn.execute(
            "UPDATE doc_summaries SET summary_embedding=?, updated_at=? WHERE id=?",
            (json.dumps(embedding), now, id),
        )
        updated = cursor.rowcount > 0
        conn.commit()
        return updated


def get_embeddings_by_kb(knowledge_base: str, status: str = "generated") -> list[dict]:
    """按知识库获取摘要及其嵌入向量，用于分层检索的预计算匹配

    Returns:
        list[dict]: 每条记录包含 id, doc_id, summary, summary_embedding 字段
    """
    import json as _json
    with _instance._get_store().connect() as conn:
        rows = conn.execute(
            "SELECT id, doc_id, summary, summary_embedding FROM doc_summaries "
            "WHERE knowledge_base=? AND status=? ORDER BY created_at DESC",
            (knowledge_base, status),
        ).fetchall()

    results = []
    for row in rows:
        r = dict(row)
        # 解码嵌入向量
        raw_emb = r.get("summary_embedding")
        if raw_emb:
            try:
                r["summary_embedding"] = _json.loads(raw_emb)
            except (json.JSONDecodeError, TypeError):
                r["summary_embedding"] = None
        results.append(r)
    return results


def update_status(id: str, status: str) -> bool:
    """更新摘要状态。"""
    now = datetime.now().isoformat()
    with _instance._get_store().connect() as conn:
        cursor = conn.execute(
            "UPDATE doc_summaries SET status=?, updated_at=? WHERE id=?",
            (status, now, id),
        )
        updated = cursor.rowcount > 0
        conn.commit()
        return updated


def get_by_kb(knowledge_base: str, status: Optional[str] = None) -> list[dict]:
    """按知识库查询摘要，可按状态过滤。"""
    with _instance._get_store().connect() as conn:
        if status is not None:
            rows = conn.execute(
                "SELECT * FROM doc_summaries WHERE knowledge_base=? AND status=? ORDER BY created_at DESC",
                (knowledge_base, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM doc_summaries WHERE knowledge_base=? ORDER BY created_at DESC",
                (knowledge_base,),
            ).fetchall()
        return [dict(r) for r in rows]


def update(id: str, summary: str, status: str) -> bool:
    """更新摘要内容和状态。"""
    now = datetime.now().isoformat()
    with _instance._get_store().connect() as conn:
        cursor = conn.execute(
            "UPDATE doc_summaries SET summary=?, status=?, updated_at=? WHERE id=?",
            (summary, status, now, id),
        )
        updated = cursor.rowcount > 0
        conn.commit()
        return updated


def delete(id: str) -> bool:
    """删除摘要记录。"""
    with _instance._get_store().connect() as conn:
        cursor = conn.execute("DELETE FROM doc_summaries WHERE id=?", (id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        return deleted


def delete_by_doc_id(doc_id: str) -> bool:
    """按文档 ID 删除摘要。"""
    with _instance._get_store().connect() as conn:
        cursor = conn.execute("DELETE FROM doc_summaries WHERE doc_id=?", (doc_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        return deleted


def delete_by_knowledge_base(knowledge_base: str) -> int:
    """按知识库删除摘要。"""
    with _instance._get_store().connect() as conn:
        cursor = conn.execute("DELETE FROM doc_summaries WHERE knowledge_base=?", (knowledge_base,))
        count = cursor.rowcount
        conn.commit()
        return count
