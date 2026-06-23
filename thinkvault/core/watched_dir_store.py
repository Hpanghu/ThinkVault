"""
监听目录配置存储 — 管理文件系统监听目录
"""

import uuid
from datetime import datetime
from typing import Optional

from thinkvault.core.base_store import BaseStore
from thinkvault.utils.logger import logger

WATCHED_DIRS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS watched_dirs (
        id TEXT PRIMARY KEY,
        directory_path TEXT NOT NULL UNIQUE,
        knowledge_base TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        last_scan_at TEXT,
        file_count INTEGER NOT NULL DEFAULT 0
    )
"""

_MIGRATIONS: list[str] = []


class _Store(BaseStore):
    _SCHEMA = WATCHED_DIRS_SCHEMA
    _MIGRATIONS = _MIGRATIONS


_instance = _Store()


def add(directory_path: str, knowledge_base: str) -> str:
    """添加监听目录，返回 id。"""
    item_id = uuid.uuid4().hex
    now = datetime.now().isoformat()
    with _instance._get_store().connect() as conn:
        conn.execute(
            "INSERT INTO watched_dirs (id, directory_path, knowledge_base, enabled, "
            "created_at, last_scan_at, file_count) VALUES (?, ?, ?, 1, ?, NULL, 0)",
            (item_id, directory_path, knowledge_base, now),
        )
        conn.commit()
    return item_id


def get(id: str) -> Optional[dict]:
    """获取监听目录记录。"""
    with _instance._get_store().connect() as conn:
        row = conn.execute("SELECT * FROM watched_dirs WHERE id=?", (id,)).fetchone()
        return dict(row) if row else None


def get_by_path(directory_path: str) -> Optional[dict]:
    """按路径获取监听目录记录。"""
    with _instance._get_store().connect() as conn:
        row = conn.execute("SELECT * FROM watched_dirs WHERE directory_path=?", (directory_path,)).fetchone()
        return dict(row) if row else None


def list_enabled_dirs() -> list[dict]:
    """获取所有启用的监听目录。"""
    with _instance._get_store().connect() as conn:
        rows = conn.execute(
            "SELECT * FROM watched_dirs WHERE enabled=1 ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]


def list_by_knowledge_base(knowledge_base: str) -> list[dict]:
    """按知识库列出监听目录。"""
    with _instance._get_store().connect() as conn:
        rows = conn.execute(
            "SELECT * FROM watched_dirs WHERE knowledge_base=? ORDER BY created_at",
            (knowledge_base,),
        ).fetchall()
        return [dict(r) for r in rows]


def update_enabled(id: str, enabled: int) -> bool:
    """启用或禁用监听目录。"""
    with _instance._get_store().connect() as conn:
        cursor = conn.execute(
            "UPDATE watched_dirs SET enabled=? WHERE id=?",
            (enabled, id),
        )
        updated = cursor.rowcount > 0
        conn.commit()
        return updated


def update_last_scan(id: str, file_count: Optional[int] = None) -> bool:
    """更新最后扫描时间。"""
    now = datetime.now().isoformat()
    with _instance._get_store().connect() as conn:
        if file_count is not None:
            cursor = conn.execute(
                "UPDATE watched_dirs SET last_scan_at=?, file_count=? WHERE id=?",
                (now, file_count, id),
            )
        else:
            cursor = conn.execute(
                "UPDATE watched_dirs SET last_scan_at=? WHERE id=?",
                (now, id),
            )
        updated = cursor.rowcount > 0
        conn.commit()
        return updated


def update_scan_time(id: str, file_count: int) -> bool:
    """更新扫描时间和文件数量。"""
    now = datetime.now().isoformat()
    with _instance._get_store().connect() as conn:
        cursor = conn.execute(
            "UPDATE watched_dirs SET last_scan_at=?, file_count=? WHERE id=?",
            (now, file_count, id),
        )
        updated = cursor.rowcount > 0
        conn.commit()
        return updated


def set_enabled(id: str, enabled: int) -> bool:
    """启用或禁用监听目录。"""
    with _instance._get_store().connect() as conn:
        cursor = conn.execute(
            "UPDATE watched_dirs SET enabled=? WHERE id=?",
            (enabled, id),
        )
        updated = cursor.rowcount > 0
        conn.commit()
        return updated


def delete(id: str) -> bool:
    """删除监听目录记录。"""
    with _instance._get_store().connect() as conn:
        cursor = conn.execute("DELETE FROM watched_dirs WHERE id=?", (id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        return deleted


def delete_by_knowledge_base(knowledge_base: str) -> int:
    """按知识库删除监听目录。"""
    with _instance._get_store().connect() as conn:
        cursor = conn.execute("DELETE FROM watched_dirs WHERE knowledge_base=?", (knowledge_base,))
        count = cursor.rowcount
        conn.commit()
        return count


# 兼容旧方法别名
set_enabled = update_enabled
update_scan_time = update_last_scan
