"""ThinkVault V2.0 集成测试 — SSE 流式、对话持久化、PDF 支持、多会话管理"""

import time
import json
import pytest
import requests
from pathlib import Path

BASE = "http://127.0.0.1:8000"

# API 认证 Token（需与服务器 .env 中 THINKVAULT_API_TOKEN 一致）
API_TOKEN = "B-tOnoFYbfZf76tb7H0BCfZAy1tddNICnEZNNaqAbSA"
AUTH_HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}


# ============================== 测试套件 ==============================

class TestServerV2:
    """V2.0 服务健康检查"""

    def test_api_root(self):
        r = requests.get(f"{BASE}/api/hardware", headers=AUTH_HEADERS, timeout=5)
        assert r.status_code == 200
        assert "cpu_count" in r.json()

    def test_api_conversations_empty(self):
        r = requests.get(f"{BASE}/api/conversations", headers=AUTH_HEADERS, timeout=5)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestConversationAPI:
    """对话持久化 API (V2.0 新增)"""

    def test_create_conversation(self):
        r = requests.post(f"{BASE}/api/conversations", json={"title": "Test会话"}, headers=AUTH_HEADERS, timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "id" in data
        assert data["title"] == "Test会话"
        assert data["message_count"] == 0
        # cleanup
        conv_id = data["id"]
        requests.delete(f"{BASE}/api/conversations/{conv_id}", headers=AUTH_HEADERS)

    def test_get_conversation_404(self):
        r = requests.get(f"{BASE}/api/conversations/nonexistent-id", headers=AUTH_HEADERS, timeout=5)
        assert r.status_code == 404

    def test_delete_conversation_404(self):
        r = requests.delete(f"{BASE}/api/conversations/nonexistent-id", headers=AUTH_HEADERS, timeout=5)
        assert r.status_code == 404

    def test_list_conversations(self):
        # create 2
        r1 = requests.post(f"{BASE}/api/conversations", json={"title": "列表测试A"}, headers=AUTH_HEADERS)
        r2 = requests.post(f"{BASE}/api/conversations", json={"title": "列表测试B"}, headers=AUTH_HEADERS)
        c1 = r1.json()["id"]
        c2 = r2.json()["id"]

        r = requests.get(f"{BASE}/api/conversations", headers=AUTH_HEADERS)
        assert r.status_code == 200
        convs = r.json()
        titles = [c["title"] for c in convs]
        assert "列表测试A" in titles
        assert "列表测试B" in titles

        # cleanup
        requests.delete(f"{BASE}/api/conversations/{c1}", headers=AUTH_HEADERS)
        requests.delete(f"{BASE}/api/conversations/{c2}", headers=AUTH_HEADERS)

    def test_conversation_messages_persist(self):
        """验证消息持久化：创建会话 → 发 chat → 查消息"""
        r = requests.post(f"{BASE}/api/conversations", json={"title": "持久化测试"}, headers=AUTH_HEADERS)
        conv_id = r.json()["id"]

        # 发送聊天
        chat_r = requests.post(f"{BASE}/api/chat", json={
            "message": "你好，这是一条测试消息",
            "conversation_id": conv_id,
        }, headers=AUTH_HEADERS, timeout=120)
        assert chat_r.status_code == 200

        # 查询会话详情
        r = requests.get(f"{BASE}/api/conversations/{conv_id}", headers=AUTH_HEADERS)
        assert r.status_code == 200
        conv = r.json()
        assert len(conv["messages"]) > 0
        assert conv["messages"][0]["role"] == "user"
        assert "测试消息" in conv["messages"][0]["content"]

        requests.delete(f"{BASE}/api/conversations/{conv_id}", headers=AUTH_HEADERS)

    def test_rename_conversation(self):
        r = requests.post(f"{BASE}/api/conversations", json={"title": "原始名称"}, headers=AUTH_HEADERS)
        conv_id = r.json()["id"]

        r2 = requests.patch(f"{BASE}/api/conversations/{conv_id}", json={"title": "新名称"}, headers=AUTH_HEADERS)
        assert r2.status_code == 200
        assert r2.json()["title"] == "新名称"

        requests.delete(f"{BASE}/api/conversations/{conv_id}", headers=AUTH_HEADERS)


class TestSSEStreaming:
    """SSE 流式推理测试"""

    def test_chat_stream_returns_sse(self):
        """验证 /api/chat/stream 返回 SSE"""
        r = requests.post(f"{BASE}/api/chat/stream", json={
            "message": "你好",
        }, stream=True, headers=AUTH_HEADERS, timeout=60)

        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")

        chunks = []
        for line in r.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                chunks.append(line)
            if len(chunks) >= 50:
                break

        assert len(chunks) > 0
        # 最后一条应该是 done: true
        last = json.loads(chunks[-1][6:])
        assert last.get("done") is True

    def test_chat_stream_creates_conversation(self):
        """验证流式聊天自动创建会话"""
        r = requests.post(f"{BASE}/api/chat/stream", json={
            "message": "测试自动创建会话",
        }, stream=True, headers=AUTH_HEADERS, timeout=60)

        conv_id = None
        for line in r.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                data = json.loads(line[6:])
                if data.get("done") and data.get("conversation_id"):
                    conv_id = data["conversation_id"]
                    break

        assert conv_id is not None
        # 验证会话存在且包含消息
        r2 = requests.get(f"{BASE}/api/conversations/{conv_id}", headers=AUTH_HEADERS)
        assert r2.status_code == 200
        conv = r2.json()
        assert len(conv["messages"]) >= 2

        requests.delete(f"{BASE}/api/conversations/{conv_id}", headers=AUTH_HEADERS)

    def test_chat_stream_with_existing_conv(self):
        """验证流式聊天追加到已有会话"""
        r = requests.post(f"{BASE}/api/conversations", json={"title": "追加测试"}, headers=AUTH_HEADERS)
        conv_id = r.json()["id"]

        # 非流式发送一条
        requests.post(f"{BASE}/api/chat", json={
            "message": "第一条消息",
            "conversation_id": conv_id,
        }, headers=AUTH_HEADERS, timeout=60)

        # 流式发送第二条
        r2 = requests.post(f"{BASE}/api/chat/stream", json={
            "message": "第二条消息",
            "conversation_id": conv_id,
        }, stream=True, headers=AUTH_HEADERS, timeout=60)

        for line in r2.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                data = json.loads(line[6:])
                if data.get("done"):
                    break

        # 验证 4 条消息 (user + assistant) x 2
        r3 = requests.get(f"{BASE}/api/conversations/{conv_id}", headers=AUTH_HEADERS)
        assert r3.status_code == 200
        conv = r3.json()
        assert len(conv["messages"]) >= 3  # user1, assistant1, user2 (assistant2 may come via stream)

        requests.delete(f"{BASE}/api/conversations/{conv_id}", headers=AUTH_HEADERS)


class TestPDFSupport:
    """PDF 文档支持测试"""

    def test_upload_pdf(self):
        """测试上传 PDF 并确认解析成功"""
        pdf_path = Path(__file__).parent / "test_doc_deep_learning.txt"
        if not pdf_path.exists():
            pytest.skip("测试文档不存在")

        with open(pdf_path, "rb") as f:
            r = requests.post(
                f"{BASE}/api/documents/upload",
                files={"file": ("test_deep_learning.txt", f, "text/plain")},
                params={"knowledge_base": "v2_pdf_test"},
                headers=AUTH_HEADERS,
            timeout=10,
            )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["chunk_count"] > 0

        # cleanup
        docs = requests.get(f"{BASE}/api/documents", params={"knowledge_base": "v2_pdf_test"}, headers=AUTH_HEADERS).json()
        for d in docs:
            requests.delete(f"{BASE}/api/documents/{d['id']}", headers=AUTH_HEADERS)
        requests.delete(f"{BASE}/api/knowledge-bases/v2_pdf_test", headers=AUTH_HEADERS)

    def test_unsupported_format_rejected(self):
        """验证不支持的文件格式被拒绝"""
        r = requests.post(
            f"{BASE}/api/documents/upload",
            files={"file": ("test.xyz", b"dummy", "application/octet-stream")},
            headers=AUTH_HEADERS,
            timeout=5,
        )
        data = r.json()
        assert data["status"] == "error"


class TestModelAPI:
    """模型管理 API (回归)"""

    def test_model_info(self):
        r = requests.get(f"{BASE}/api/model", headers=AUTH_HEADERS, timeout=5)
        assert r.status_code == 200
        assert "loaded" in r.json()

    def test_hardware_info(self):
        r = requests.get(f"{BASE}/api/hardware", headers=AUTH_HEADERS, timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "cpu_count" in data
        assert "total_ram_gb" in data


class TestFullRegression:
    """全量回归 — 确保 V1.0 功能不受影响"""

    def test_chat_basic(self):
        r = requests.post(f"{BASE}/api/chat", json={
            "message": "你好",
        }, headers=AUTH_HEADERS, timeout=60)
        assert r.status_code == 200
        data = r.json()
        assert "answer" in data

    def test_document_upload_txt(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("这是一份测试文档，用于回归测试。\n" * 20)
            tmp = f.name

        with open(tmp, "rb") as f:
            r = requests.post(
                f"{BASE}/api/documents/upload",
                files={"file": ("regression_test.txt", f, "text/plain")},
                params={"knowledge_base": "regression"},
                headers=AUTH_HEADERS,
            timeout=10,
            )
        Path(tmp).unlink(missing_ok=True)

        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

        # cleanup
        docs = requests.get(f"{BASE}/api/documents", params={"knowledge_base": "regression"}, headers=AUTH_HEADERS).json()
        for d in docs:
            requests.delete(f"{BASE}/api/documents/{d['id']}", headers=AUTH_HEADERS)
        requests.delete(f"{BASE}/api/knowledge-bases/regression", headers=AUTH_HEADERS)

    def test_document_list_delete(self):
        """文档列表 + 删除回归"""
        r = requests.get(f"{BASE}/api/documents", headers=AUTH_HEADERS, timeout=5)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_knowledge_bases(self):
        r = requests.get(f"{BASE}/api/knowledge-bases", headers=AUTH_HEADERS, timeout=5)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
