"""
单元测试：对话持久化存储 (core/conversation_store.py)
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from thinkvault.core.conversation_store import (
    create_conversation, list_conversations, get_conversation,
    update_conversation, delete_conversation,
    add_message, get_messages, delete_messages, _store,
)
from thinkvault.core.db import SqliteStore


@pytest.fixture(autouse=True)
def cleanup():
    yield
    # 确保关闭所有连接
    global _store
    if _store is not None:
        _store.close()
        _store = None
    import gc
    gc.collect()
    db_path = Path.home() / ".thinkvault" / "conversations.db"
    for _ in range(5):
        try:
            if db_path.exists():
                db_path.unlink()
            break
        except PermissionError:
            time.sleep(0.1)


class TestConversationStore:
    def test_create_conversation(self):
        conv = create_conversation(title="测试会话")
        assert "id" in conv
        assert len(conv["id"]) == 16
        assert conv["title"] == "测试会话"
        assert "created_at" in conv
        assert conv["message_count"] == 0

    def test_create_default_title(self):
        conv = create_conversation()
        assert conv["title"] == "New Chat"

    def test_list_conversations(self):
        create_conversation("会话A")
        create_conversation("会话B")
        convs = list_conversations()
        titles = [c["title"] for c in convs]
        assert "会话A" in titles
        assert "会话B" in titles
        assert convs[0]["title"] == "会话B"  # DESC 排序

    def test_get_conversation(self):
        conv = create_conversation("查找我")
        found = get_conversation(conv["id"])
        assert found is not None
        assert found["title"] == "查找我"
        assert found["message_count"] == 0

    def test_get_conversation_not_found(self):
        assert get_conversation("nonexistent") is None

    def test_update_conversation_title(self):
        conv = create_conversation("旧标题")
        result = update_conversation(conv["id"], title="新标题")
        assert result is True
        updated = get_conversation(conv["id"])
        assert updated["title"] == "新标题"

    def test_update_conversation_not_found(self):
        result = update_conversation("nonexistent", title="x")
        assert result is False

    def test_add_message(self):
        conv = create_conversation("消息测试")
        msg = add_message(conv["id"], "user", "你好")
        assert msg["role"] == "user"
        assert msg["content"] == "你好"
        assert msg["conv_id"] == conv["id"]

        msg2 = add_message(conv["id"], "assistant", "你好！有什么可以帮你的？")
        assert msg2["role"] == "assistant"

        found = get_conversation(conv["id"])
        assert found["message_count"] == 2

    def test_get_messages(self):
        conv = create_conversation("消息列表")
        add_message(conv["id"], "user", "第一条")
        add_message(conv["id"], "assistant", "回复一")
        add_message(conv["id"], "user", "第二条")

        msgs = get_messages(conv["id"])
        assert len(msgs) == 3
        assert msgs[0]["content"] == "第一条"
        assert msgs[1]["content"] == "回复一"
        assert msgs[2]["content"] == "第二条"

    def test_get_messages_limit(self):
        conv = create_conversation("限制测试")
        for i in range(50):
            add_message(conv["id"], "user", f"消息{i}")
        msgs = get_messages(conv["id"], limit=10)
        assert len(msgs) == 10

    def test_delete_conversation_cascade(self):
        conv = create_conversation("级联删除")
        add_message(conv["id"], "user", "将被删除的消息")

        result = delete_conversation(conv["id"])
        assert result is True
        assert get_conversation(conv["id"]) is None

        msgs = get_messages(conv["id"])
        assert len(msgs) == 0

    def test_delete_conversation_not_found(self):
        result = delete_conversation("nonexistent")
        assert result is False

    def test_delete_messages(self):
        conv = create_conversation("清空消息")
        add_message(conv["id"], "user", "A")
        add_message(conv["id"], "assistant", "B")
        count = delete_messages(conv["id"])
        assert count == 2
        assert len(get_messages(conv["id"])) == 0

    def test_message_role_constraint(self):
        conv = create_conversation("角色约束")
        with pytest.raises(Exception):
            add_message(conv["id"], "invalid_role", "内容")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
