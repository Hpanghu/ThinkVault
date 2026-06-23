"""
对话持久化存储 — SQLite 管理多会话和消息历史
"""

import uuid
from datetime import datetime
from typing import Optional

from thinkvault.core.base_store import BaseStore
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

# 增量迁移：为已有表添加新列（向后兼容）
_MIGRATIONS = [
    "ALTER TABLE messages ADD COLUMN sources TEXT DEFAULT '[]'",
    "ALTER TABLE messages ADD COLUMN mode TEXT DEFAULT 'chat'",
    "ALTER TABLE conversations ADD COLUMN role_id TEXT DEFAULT ''",
]


class _Store(BaseStore):
    _SCHEMA = CONVERSATIONS_SCHEMA
    _MIGRATIONS = _MIGRATIONS


_instance = _Store()


# ============================== 会话 CRUD ==============================

def create_conversation(title: str = "New Chat", role_id: str = "") -> dict:
    conv_id = uuid.uuid4().hex[:16]
    now = datetime.now().isoformat()
    with _instance._get_store().connect() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at, role_id) VALUES (?, ?, ?, ?, ?)",
            (conv_id, title, now, now, role_id),
        )
        conn.commit()
    logger.info(f"创建会话: {conv_id} ({title}) [角色: {role_id}]")
    return {"id": conv_id, "title": title, "created_at": now, "role_id": role_id, "message_count": 0}


def list_conversations(limit: int = 30, offset: int = 0) -> list[dict]:
    with _instance._get_store().connect() as conn:
        rows = conn.execute("""
            SELECT c.id, c.title, c.created_at, c.updated_at, c.role_id,
                   (SELECT COUNT(*) FROM messages m WHERE m.conv_id=c.id) AS message_count
            FROM conversations c
            ORDER BY c.updated_at DESC
            LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()
        return [dict(r) for r in rows]


def count_conversations() -> int:
    with _instance._get_store().connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM conversations").fetchone()
        return row["cnt"] if row else 0


def get_conversation(conv_id: str) -> Optional[dict]:
    with _instance._get_store().connect() as conn:
        row = conn.execute("""
            SELECT c.*,
                   (SELECT COUNT(*) FROM messages m WHERE m.conv_id=c.id) AS message_count
            FROM conversations c
            WHERE c.id=?
        """, (conv_id,)).fetchone()
        return dict(row) if row else None


def update_conversation(conv_id: str, title: Optional[str] = None) -> bool:
    now = datetime.now().isoformat()
    with _instance._get_store().connect() as conn:
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


def update_conversation_role(conv_id: str, role_id: str) -> bool:
    with _instance._get_store().connect() as conn:
        cursor = conn.execute(
            "UPDATE conversations SET role_id=? WHERE id=?",
            (role_id, conv_id),
        )
        updated = cursor.rowcount > 0
        conn.commit()
    return updated


def batch_update_conversations_role(old_role_id: str, new_role_id: str) -> int:
    """批量更新使用某个角色的所有会话为新角色"""
    with _instance._get_store().connect() as conn:
        cursor = conn.execute(
            "UPDATE conversations SET role_id=? WHERE role_id=?",
            (new_role_id, old_role_id),
        )
        count = cursor.rowcount
        conn.commit()
    return count


def delete_conversation(conv_id: str) -> bool:
    with _instance._get_store().connect() as conn:
        conn.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
        cursor = conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
    if deleted:
        logger.info(f"删除会话: {conv_id}")
    return deleted


def delete_all_conversations() -> int:
    """删除所有会话及其消息，返回删除的会话数量"""
    with _instance._get_store().connect() as conn:
        # 先统计数量
        count_row = conn.execute("SELECT COUNT(*) AS cnt FROM conversations").fetchone()
        count = count_row["cnt"] if count_row else 0
        # 删除所有消息和会话
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM conversations")
        conn.commit()
    logger.info(f"删除所有会话: 共 {count} 条")
    return count


# ============================== 消息 CRUD ==============================

def add_message(conv_id: str, role: str, content: str, sources: str = "[]", mode: str = "chat") -> dict:
    msg_id = uuid.uuid4().hex[:16]
    now = datetime.now().isoformat()
    with _instance._get_store().connect() as conn:
        conn.execute(
            "INSERT INTO messages (id, conv_id, role, content, created_at, sources, mode) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (msg_id, conv_id, role, content, now, sources, mode),
        )
        conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conv_id))
        conn.commit()
    return {"id": msg_id, "conv_id": conv_id, "role": role, "content": content, "created_at": now, "sources": sources, "mode": mode}


def get_messages(conv_id: str, limit: int = 200) -> list[dict]:
    with _instance._get_store().connect() as conn:
        rows = conn.execute(
            "SELECT id, conv_id, role, content, created_at FROM messages WHERE conv_id=? ORDER BY created_at ASC LIMIT ?",
            (conv_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_messages(conv_id: str) -> int:
    with _instance._get_store().connect() as conn:
        cursor = conn.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
        count = cursor.rowcount
        conn.commit()
        return count


def get_recent_messages(conversation_id: str, limit: int = 10) -> list[dict]:
    """获取会话最近的消息。"""
    with _instance._get_store().connect() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conv_id=? ORDER BY created_at DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
        # 按时间正序返回
        return [dict(r) for r in reversed(rows)]
