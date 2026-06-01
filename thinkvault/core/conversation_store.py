"""
对话持久化存储 — SQLite 管理多会话和消息历史
"""

import uuid
from datetime import datetime
from typing import Optional

from thinkvault.core.db import SqliteStore
from thinkvault.utils.logger import logger

CONVERSATIONS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL DEFAULT 'New Chat',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        conv_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (conv_id) REFERENCES conversations(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_messages_conv_id
    ON messages(conv_id)
"""

_store = None  # 惰性初始化，避免 import 时立即连接数据库


def _get_store() -> SqliteStore:
    """惰性获取 SQLite 存储实例（线程安全）"""
    global _store
    if _store is None:
        _store = SqliteStore("conversations.db")
        _store.init_schema(CONVERSATIONS_SCHEMA)
    return _store


# ============================== 会话 CRUD ==============================

def create_conversation(title: str = "New Chat") -> dict:
    conv_id = uuid.uuid4().hex[:16]  # 64-bit 熵值
    now = datetime.now().isoformat()
    with _get_store().connect() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (conv_id, title, now, now),
        )
        conn.commit()
    logger.info(f"创建会话: {conv_id} ({title})")
    return {"id": conv_id, "title": title, "created_at": now, "message_count": 0}


def list_conversations() -> list[dict]:
    with _get_store().connect() as conn:
        rows = conn.execute("""
            SELECT c.id, c.title, c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM messages m WHERE m.conv_id=c.id) AS message_count
            FROM conversations c
            ORDER BY c.updated_at DESC
        """).fetchall()
        return [dict(r) for r in rows]


def get_conversation(conv_id: str) -> Optional[dict]:
    with _get_store().connect() as conn:
        row = conn.execute("""
            SELECT c.*,
                   (SELECT COUNT(*) FROM messages m WHERE m.conv_id=c.id) AS message_count
            FROM conversations c
            WHERE c.id=?
        """, (conv_id,)).fetchone()
        return dict(row) if row else None


def update_conversation(conv_id: str, title: Optional[str] = None) -> bool:
    now = datetime.now().isoformat()
    with _get_store().connect() as conn:
        if title is not None:
            cursor = conn.execute(
                "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
                (title, now, conv_id),
            )
        else:
            cursor = conn.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?",
                (now, conv_id),
            )
        # P3 修复：用 cursor.rowcount 而非 conn.total_changes（累计值）
        updated = cursor.rowcount > 0
        conn.commit()
        return updated


def delete_conversation(conv_id: str) -> bool:
    with _get_store().connect() as conn:
        conn.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
        cursor = conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
    if deleted:
        logger.info(f"删除会话: {conv_id}")
    return deleted


# ============================== 消息 CRUD ==============================

def add_message(conv_id: str, role: str, content: str) -> dict:
    msg_id = uuid.uuid4().hex[:16]
    now = datetime.now().isoformat()
    with _get_store().connect() as conn:
        conn.execute(
            "INSERT INTO messages (id, conv_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (msg_id, conv_id, role, content, now),
        )
        conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conv_id))
        conn.commit()
    return {"id": msg_id, "conv_id": conv_id, "role": role, "content": content, "created_at": now}


def get_messages(conv_id: str, limit: int = 200) -> list[dict]:
    with _get_store().connect() as conn:
        rows = conn.execute(
            "SELECT id, conv_id, role, content, created_at FROM messages WHERE conv_id=? ORDER BY created_at ASC LIMIT ?",
            (conv_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_messages(conv_id: str) -> int:
    with _get_store().connect() as conn:
        cursor = conn.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
        count = cursor.rowcount
        conn.commit()
        return count
