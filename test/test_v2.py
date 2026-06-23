"""ThinkVault V2.0 集成测试（TestClient 版本）

⚠️ 已弃用：本文件功能与 test_api_integration.py 高度重复，且存在 14 个失败测试。
请使用 test_api_integration.py 替代。

使用 FastAPI TestClient，无需启动真实服务器。
运行方式:
    cd D:/ThinkVault
    python -m pytest test/test_v2.py -v
"""

import pytest

# 整体跳过：功能已被 test_api_integration.py 完整覆盖
pytestmark = pytest.mark.skip(reason="已弃用：功能与 test_api_integration.py 重复，请使用 test_api_integration.py")

import sys
import os
import io
import json
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def setup_env():
    """设置测试环境（禁用认证、Mock 外部依赖）"""
    os.environ["THINKVAULT_DISABLE_AUTH"] = "1"
    os.environ["THINKVAULT_API_TOKEN"] = ""
    os.environ["THINKVAULT_SKIP_RERANK"] = "1"
    yield
    os.environ.pop("THINKVAULT_DISABLE_AUTH", None)


@pytest.fixture(scope="module")
def mock_container():
    """Mock container 中的所有外部依赖"""
    with patch("thinkvault.core.container.container") as mock_cont:
        # Mock thinkvault_llm
        mock_llm = MagicMock()
        mock_llm.is_loaded = True
        mock_llm.base_url = "http://localhost:8080/v1"
        mock_llm.model = "default"
        mock_llm.generate = AsyncMock(return_value=("这是一个测试回答。", {"output_tokens": 10, "tokens_per_sec": 5.0}))
        # 让 generate_stream 返回异步生成器（而非协程）
        async def _mock_stream():
            async for item in _mock_stream_generator():
                yield item
        mock_llm.generate_stream = MagicMock(side_effect=lambda *a, **kw: _mock_stream())
        mock_llm._check_availability = AsyncMock(return_value=True)
        mock_cont.thinkvault_llm = mock_llm

        # Mock embedder
        mock_emb = MagicMock()
        mock_emb.embed_texts = MagicMock(return_value=[[0.1] * 1024] * 5)
        mock_emb.embed_query = MagicMock(return_value=[0.1] * 1024)
        mock_cont.embedder = mock_emb

        # Mock vector_store
        mock_vs = MagicMock()
        mock_vs.list_knowledge_bases.return_value = ["default", "test_kb"]
        mock_vs.get_chunk_count.return_value = 100
        mock_vs.get_or_create_collection.return_value = MagicMock()
        mock_vs.delete_knowledge_base.return_value = None
        mock_cont.vector_store = mock_vs

        # Mock retriever
        mock_ret = MagicMock()
        mock_ret.should_retrieve.return_value = True
        mock_ret.retrieve_smart.return_value = {
            "results": [
                {
                    "text": "Transformer 是一种基于自注意力机制的神经网络架构。",
                    "metadata": {"source_file": "test.txt", "source_page": 1},
                    "distance": 0.5,
                }
            ],
            "conversation_context": "",
        }
        mock_ret.format_context.return_value = (
            "Transformer 是一种基于自注意力机制的神经网络架构。",
            ["test.txt"],
        )
        mock_ret.invalidate_cache.return_value = None
        mock_cont.retriever = mock_ret

        # Mock document_store
        mock_ds = MagicMock()
        mock_ds.add_document.return_value = "doc_12345"
        mock_ds.get_document.return_value = {
            "id": "doc_12345",
            "file_name": "test.txt",
            "file_type": "txt",
            "file_size": 100,
            "knowledge_base": "default",
            "chunk_count": 5,
            "uploaded_at": "2026-06-07T00:00:00",
        }
        mock_ds.list_documents.return_value = [
            {"id": "doc_12345", "file_name": "test.txt", "file_type": "txt", "chunk_count": 5}
        ]
        mock_ds.delete_document.return_value = True
        mock_ds.count_documents.return_value = 1
        mock_cont.document_store = mock_ds

        # Mock conversation_store
        mock_cs = MagicMock()
        mock_cs.create_conversation.return_value = "conv_12345"
        mock_cs.get_conversation.return_value = {
            "id": "conv_12345",
            "title": "Test Conversation",
            "created_at": "2026-06-07T00:00:00",
            "updated_at": "2026-06-07T00:00:00",
        }
        mock_cs.list_conversations.return_value = [
            {"id": "conv_12345", "title": "Test", "updated_at": "2026-06-07T00:00:00"}
        ]
        mock_cs.get_messages.return_value = [
            {"role": "user", "content": "你好", "timestamp": "2026-06-07T00:00:00"}
        ]
        mock_cs.delete_conversation.return_value = True
        mock_cs.count_conversations.return_value = 1
        mock_cs.update_conversation.return_value = True
        mock_cont.conversation_store = mock_cs

        # Mock doc_summary_store
        mock_ss = MagicMock()
        mock_ss.get_summaries_by_kb.return_value = []
        mock_cont.doc_summary_store = mock_ss

        yield mock_cont


@pytest.fixture(scope="module")
def client(mock_container):
    """创建 TestClient（进程内测试，无需启动服务器）"""
    from thinkvault.api.server import create_app
    import thinkvault.api.server as srv
    srv.THINKVAULT_API_TOKEN = ""
    app = create_app()
    with TestClient(app) as c:
        yield c


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

async def _mock_stream_generator():
    """模拟 LLM 流式输出"""
    yield {"token": "这是", "done": False}
    yield {"token": "一个", "done": False}
    yield {"token": "测试。", "done": False}
    yield {"token": "", "done": True, "stats": {"output_tokens": 10, "tokens_per_sec": 5.0}}


def _auth_headers():
    """返回认证头（测试环境中禁用认证，但保留接口）"""
    return {"Authorization": "Bearer test_token"}


# ── 1. 服务健康检查 ──────────────────────────────────────────────────────────

class TestServerV2:
    """V2.0 服务健康检查"""

    def test_api_root(self, client):
        """访问根路径"""
        resp = client.get("/")
        assert resp.status_code == 200

    def test_api_hardware(self, client):
        """硬件检测 API 可用"""
        resp = client.get("/api/hardware", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "cpu_count" in data
        assert "total_ram_gb" in data

    def test_api_model_info(self, client):
        """模型状态 API 可用"""
        resp = client.get("/api/model", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "loaded" in data
        assert "model_path" in data

    def test_conversations_empty(self, client):
        """会话列表（空）"""
        resp = client.get("/api/conversations", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert isinstance(data["items"], list)


# ── 2. 会话管理 API (V2.0 新增) ────────────────────────────────────────

class TestConversationAPI:
    """对话持久化 API (V2.0 新增)"""

    def test_create_conversation(self, client):
        """创建新会话"""
        resp = client.post(
            "/api/conversations",
            json={"title": "Test会话"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["title"] == "Test会话"
        assert data["message_count"] == 0

        # cleanup
        client.delete(f"/api/conversations/{data['id']}", headers=_auth_headers())

    def test_get_conversation_404(self, client):
        """获取不存在的会话应返回 404"""
        resp = client.get("/api/conversations/nonexistent-id", headers=_auth_headers())
        assert resp.status_code == 404

    def test_delete_conversation_404(self, client):
        """删除不存在的会话应返回 404"""
        resp = client.delete("/api/conversations/nonexistent-id", headers=_auth_headers())
        assert resp.status_code == 404

    def test_list_conversations(self, client):
        """分页获取会话列表"""
        resp = client.get("/api/conversations", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    def test_conversation_messages_persist(self, client):
        """验证消息持久化：创建会话 → 发 chat → 查消息"""
        # 创建会话
        r = client.post(
            "/api/conversations",
            json={"title": "持久化测试"},
            headers=_auth_headers(),
        )
        assert r.status_code == 200
        conv_id = r.json()["id"]

        # 发送聊天（非流式）
        chat_r = client.post(
            "/api/chat",
            json={"message": "你好，这是一条测试消息", "conversation_id": conv_id},
            headers=_auth_headers(),
        )
        assert chat_r.status_code == 200
        chat_data = chat_r.json()
        assert "answer" in chat_data

        # 查询会话详情（应包含消息）
        r2 = client.get(f"/api/conversations/{conv_id}", headers=_auth_headers())
        assert r2.status_code == 200
        conv = r2.json()
        assert "messages" in conv
        assert len(conv["messages"]) > 0
        assert conv["messages"][0]["role"] == "user"
        assert "测试消息" in conv["messages"][0]["content"]

        # cleanup
        client.delete(f"/api/conversations/{conv_id}", headers=_auth_headers())

    def test_rename_conversation(self, client):
        """重命名会话"""
        # 创建会话
        r = client.post(
            "/api/conversations",
            json={"title": "原始名称"},
            headers=_auth_headers(),
        )
        conv_id = r.json()["id"]

        # 重命名
        r2 = client.patch(
            f"/api/conversations/{conv_id}",
            json={"title": "新名称"},
            headers=_auth_headers(),
        )
        assert r2.status_code == 200
        assert r2.json()["title"] == "新名称"

        # cleanup
        client.delete(f"/api/conversations/{conv_id}", headers=_auth_headers())

    def test_delete_conversation(self, client):
        """删除会话"""
        # 创建会话
        r = client.post(
            "/api/conversations",
            json={"title": "待删除"},
            headers=_auth_headers(),
        )
        conv_id = r.json()["id"]

        # 删除
        r2 = client.delete(f"/api/conversations/{conv_id}", headers=_auth_headers())
        assert r2.status_code == 200
        assert r2.json()["status"] == "ok"


# ── 3. SSE 流式推理 ──────────────────────────────────────────────────────────

class TestSSEStreaming:
    """SSE 流式推理测试"""

    def test_chat_stream_returns_sse(self, client):
        """验证 /api/chat/stream 返回 SSE"""
        resp = client.post(
            "/api/chat/stream",
            json={"message": "你好"},
            headers={**_auth_headers(), "Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        # 解析 SSE 流
        lines = resp.text.strip().split("\n")
        assert len(lines) > 0
        # 第一行应是 SSE data:
        assert lines[0].startswith("data:")

    def test_chat_stream_creates_conversation(self, client):
        """验证流式聊天自动创建会话"""
        resp = client.post(
            "/api/chat/stream",
            json={"message": "测试自动创建会话"},
            headers={**_auth_headers(), "Accept": "text/event-stream"},
        )
        assert resp.status_code == 200

        # 解析 SSE 流，找到 conversation_id
        conv_id = None
        for line in resp.text.strip().split("\n"):
            if line.startswith("data:"):
                data = json.loads(line[6:])
                if data.get("done") and data.get("conversation_id"):
                    conv_id = data["conversation_id"]
                    break

        assert conv_id is not None

        # 验证会话存在且包含消息
        r2 = client.get(f"/api/conversations/{conv_id}", headers=_auth_headers())
        assert r2.status_code == 200
        conv = r2.json()
        assert len(conv["messages"]) >= 2

        # cleanup
        client.delete(f"/api/conversations/{conv_id}", headers=_auth_headers())

    def test_chat_stream_with_existing_conv(self, client):
        """验证流式聊天追加到已有会话"""
        # 先创建会话
        r = client.post(
            "/api/conversations",
            json={"title": "追加测试"},
            headers=_auth_headers(),
        )
        conv_id = r.json()["id"]

        # 非流式发送一条
        client.post(
            "/api/chat",
            json={"message": "第一条消息", "conversation_id": conv_id},
            headers=_auth_headers(),
        )

        # 流式发送第二条
        r2 = client.post(
            "/api/chat/stream",
            json={"message": "第二条消息", "conversation_id": conv_id},
            headers={**_auth_headers(), "Accept": "text/event-stream"},
        )
        assert r2.status_code == 200

        # 验证消息数（user1 + assistant1 + user2 + assistant2 = 4）
        r3 = client.get(f"/api/conversations/{conv_id}", headers=_auth_headers())
        assert r3.status_code == 200
        conv = r3.json()
        assert len(conv["messages"]) >= 3

        # cleanup
        client.delete(f"/api/conversations/{conv_id}", headers=_auth_headers())


# ── 4. PDF 文档支持 ────────────────────────────────────────────────────────

class TestPDFSupport:
    """PDF 文档支持测试"""

    def test_upload_txt(self, client):
        """上传 TXT 文档（模拟 PDF 测试）"""
        content = "这是一个测试文档。\n\n第二行内容。"
        files = {"file": ("test.txt", content.encode("utf-8"), "text/plain")}
        data = {"knowledge_base": "default"}
        resp = client.post(
            "/api/documents/upload",
            files=files,
            data=data,
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "ok"
        assert result["file_name"] == "test.txt"
        assert result["chunk_count"] > 0

    def test_unsupported_format_rejected(self, client):
        """验证不支持的文件格式被拒绝"""
        files = {"file": ("test.xyz", b"fake binary", "application/octet-stream")}
        resp = client.post(
            "/api/documents/upload",
            files=files,
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "error"
        assert "不支持" in result.get("error", "")

    def test_upload_empty_file(self, client):
        """上传空文件"""
        files = {"file": ("empty.txt", b"", "text/plain")}
        resp = client.post(
            "/api/documents/upload",
            files=files,
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        result = resp.json()
        # 空文件可能返回 ok 或 error
        assert result["status"] in ("ok", "error")


# ── 5. 模型管理 API (回归) ────────────────────────────────────────────────

class TestModelAPI:
    """模型管理 API (回归)"""

    def test_model_info(self, client):
        """获取模型状态"""
        resp = client.get("/api/model", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "loaded" in data
        assert "model_path" in data

    def test_hardware_info(self, client):
        """硬件检测 API 可用"""
        resp = client.get("/api/hardware", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "cpu_count" in data
        assert "total_ram_gb" in data


# ── 6. 全量回归 ──────────────────────────────────────────────────────────────

class TestFullRegression:
    """全量回归 — 确保 V1.0 功能不受影响"""

    def test_chat_basic(self, client):
        """基础聊天功能"""
        resp = client.post(
            "/api/chat",
            json={"message": "你好"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert len(data["answer"]) > 0

    def test_document_upload_txt(self, client):
        """上传 TXT 文档"""
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', encoding='utf-8', delete=False) as f:
            f.write("测试内容\n" * 20)
            tmp = f.name

        try:
            with open(tmp, 'rb') as f:
                resp = client.post(
                    "/api/documents/upload",
                    files={"file": ("regression_test.txt", f, "text/plain")},
                    data={"knowledge_base": "regression"},
                    headers=_auth_headers(),
                )
            assert resp.status_code == 200
            result = resp.json()
            assert result["status"] == "ok"
        finally:
            os.unlink(tmp)

    def test_document_list_delete(self, client):
        """文档列表 + 删除回归"""
        resp = client.get("/api/documents", headers=_auth_headers())
        assert resp.status_code == 200
        assert "documents" in resp.json()

    def test_knowledge_bases(self, client):
        """知识库列表"""
        resp = client.get("/api/knowledge-bases", headers=_auth_headers())
        assert resp.status_code == 200
        assert "knowledge_bases" in resp.json()


# ── 主入口 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
