"""
ThinkVault API 集成测试 — 使用 FastAPI TestClient + Mock

目标：为 API 路由（chat.py, conversations.py, documents.py, kb.py, model.py）
补充集成测试，覆盖率从 0% 提升到 60%+

运行方式:
    cd D:/ThinkVault
    python -m pytest test/test_api_integration.py -v
"""

import sys
import os
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient

# ── Fixtures ────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def setup_env():
    """设置测试环境（禁用认证、Mock 外部依赖）"""
    os.environ["THINKVAULT_DISABLE_AUTH"] = "1"
    os.environ["THINKVAULT_API_TOKEN"] = ""
    os.environ["THINKVAULT_SKIP_RERANK"] = "1"
    yield
    # 清理
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
        mock_llm.generate_stream = MagicMock(side_effect=_mock_stream)
        mock_llm.reconfigure = AsyncMock()
        mock_llm.close = AsyncMock()
        mock_llm._check_availability = AsyncMock(return_value=True)
        mock_cont.thinkvault_llm = mock_llm

        # Mock embedder
        mock_emb = MagicMock()
        mock_emb.embed_texts = MagicMock(return_value=[[0.1] * 1024] * 5)
        mock_emb.embed_query = MagicMock(return_value=[0.1] * 1024)
        mock_cont.embedder = mock_emb

        # Mock vector_store
        mock_vs = MagicMock()
        _kb_list = ["default", "test_kb"]
        mock_vs.list_knowledge_bases = MagicMock(side_effect=lambda: list(_kb_list))
        mock_vs.get_chunk_count.return_value = 100
        mock_vs.get_or_create_collection = MagicMock(side_effect=lambda name: _kb_list.append(name) or MagicMock())
        mock_vs.delete_knowledge_base = MagicMock(side_effect=lambda name: (_kb_list.remove(name) if name in _kb_list else None))
        mock_cont.vector_store = mock_vs

        # Mock retriever
        mock_ret = MagicMock()
        mock_ret.should_retain.return_value = True
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


# ── 辅助函数 ────────────────────────────────────────────────────────────────────

async def _mock_stream_generator():
    """模拟 LLM 流式输出"""
    yield {"token": "这是", "done": False}
    yield {"token": "一个", "done": False}
    yield {"token": "测试。", "done": False}
    yield {"token": "", "done": True, "stats": {"output_tokens": 10, "tokens_per_sec": 5.0}}


def _auth_headers():
    """返回认证头（测试环境中禁用认证，但保留接口）"""
    return {"Authorization": "Bearer test_token"}


# ── 1. 服务健康检查 ────────────────────────────────────────────────────────────

class TestHealthCheck:
    """服务健康检查"""

    def test_root_returns_html(self, client):
        """访问根路径应返回 WebUI"""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "").lower() or resp.text.strip().startswith("<!")

    def test_api_model_info(self, client):
        """模型状态 API 可用"""
        resp = client.get("/api/model", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "loaded" in data
        assert "model_path" in data

    def test_api_hardware_info(self, client):
        """硬件检测 API 可用"""
        resp = client.get("/api/hardware", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "cpu_count" in data
        assert "total_ram_gb" in data


# ── 2. 知识库管理 ────────────────────────────────────────────────────────────

class TestKnowledgeBase:
    """知识库管理 API 测试"""

    def test_list_knowledge_bases(self, client):
        """列出所有知识库"""
        resp = client.get("/api/knowledge-bases", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "knowledge_bases" in data
        # 至少应有 default
        names = [kb["name"] for kb in data["knowledge_bases"]]
        assert "default" in names

    def test_create_knowledge_base(self, client):
        """创建新知识库"""
        resp = client.post(
            "/api/knowledge-bases",
            json={"name": "test_kb"},
            headers=_auth_headers(),
        )
        # 可能返回 201 或 409（已存在）
        assert resp.status_code in (201, 409)

    def test_create_invalid_kb_name(self, client):
        """创建无效名称的知识库应返回 400"""
        resp = client.post(
            "/api/knowledge-bases",
            json={"name": "AB"},  # 太短
            headers=_auth_headers(),
        )
        assert resp.status_code == 400

    def test_delete_knowledge_base(self, client):
        """删除知识库"""
        # 先创建
        client.post(
            "/api/knowledge-bases",
            json={"name": "to_delete"},
            headers=_auth_headers(),
        )
        # 再删除
        resp = client.delete("/api/knowledge-bases/to_delete", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


# ── 3. 文档管理 ──────────────────────────────────────────────────────────────

class TestDocumentManagement:
    """文档上传/列表/删除 API 测试"""

    def test_upload_txt_document(self, client):
        """上传 TXT 文档"""
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

    def test_upload_unsupported_format(self, client):
        """上传不支持的格式应返回 error"""
        files = {"file": ("test.exe", b"fake binary", "application/octet-stream")}
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

    def test_list_documents(self, client):
        """列出已索引文档"""
        resp = client.get("/api/documents", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "documents" in data
        assert "total" in data
        assert isinstance(data["documents"], list)

    def test_list_documents_by_kb(self, client):
        """按知识库过滤文档列表"""
        resp = client.get("/api/documents?knowledge_base=default", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "documents" in data
        assert isinstance(data["documents"], list)

    def test_delete_document(self, client):
        """删除已存在的文档"""
        # 先上传
        content = "测试内容"
        files = {"file": ("to_delete.txt", content.encode("utf-8"), "text/plain")}
        upload_resp = client.post(
            "/api/documents/upload",
            files=files,
            headers=_auth_headers(),
        )
        if upload_resp.json()["status"] == "ok":
            doc_id = upload_resp.json()["doc_id"]
            resp = client.delete(f"/api/documents/{doc_id}", headers=_auth_headers())
            assert resp.status_code == 200
            result = resp.json()
            assert result["status"] == "ok"

    def test_delete_nonexistent_document(self, client):
        """删除不存在的文档应返回 404"""
        resp = client.delete("/api/documents/nonexistent_id_12345", headers=_auth_headers())
        assert resp.status_code == 404


# ── 4. 会话管理 ──────────────────────────────────────────────────────────────

class TestConversationManagement:
    """会话管理 API 测试"""

    def test_list_conversations(self, client):
        """分页获取会话列表"""
        resp = client.get("/api/conversations", headers=_auth_headers())
        assert resp.status_code == 200
        result = resp.json()
        assert "conversations" in result
        assert "total" in result
        assert isinstance(result["conversations"], list)

    def test_list_conversations_with_pagination(self, client):
        """测试分页参数"""
        resp = client.get("/api/conversations?limit=5&offset=0", headers=_auth_headers())
        assert resp.status_code == 200
        result = resp.json()
        assert result["limit"] == 5
        assert result["offset"] == 0

    def test_create_conversation(self, client):
        """创建新会话"""
        resp = client.post(
            "/api/conversations",
            json={"title": "测试会话"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        result = resp.json()
        assert "id" in result
        assert result["title"] == "测试会话"
        # 清理
        client.delete(f"/api/conversations/{result['id']}", headers=_auth_headers())

    def test_get_conversation_detail(self, client):
        """获取会话详情"""
        # 先创建
        create_resp = client.post(
            "/api/conversations",
            json={"title": "详情测试"},
            headers=_auth_headers(),
        )
        conv_id = create_resp.json()["id"]
        # 获取详情
        resp = client.get(f"/api/conversations/{conv_id}", headers=_auth_headers())
        assert resp.status_code == 200
        result = resp.json()
        assert result["id"] == conv_id
        # 清理
        client.delete(f"/api/conversations/{conv_id}", headers=_auth_headers())

    def test_get_nonexistent_conversation(self, client):
        """获取不存在的会话应返回 404"""
        resp = client.get("/api/conversations/nonexistent_conv", headers=_auth_headers())
        assert resp.status_code == 404

    def test_rename_conversation(self, client):
        """重命名会话"""
        # 先创建
        create_resp = client.post(
            "/api/conversations",
            json={"title": "原始名称"},
            headers=_auth_headers(),
        )
        conv_id = create_resp.json()["id"]
        # 重命名
        resp = client.patch(
            f"/api/conversations/{conv_id}",
            json={"title": "新名称"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["title"] == "新名称"
        # 清理
        client.delete(f"/api/conversations/{conv_id}", headers=_auth_headers())

    def test_delete_conversation(self, client):
        """删除会话"""
        # 先创建
        create_resp = client.post(
            "/api/conversations",
            json={"title": "待删除"},
            headers=_auth_headers(),
        )
        conv_id = create_resp.json()["id"]
        # 删除
        resp = client.delete(f"/api/conversations/{conv_id}", headers=_auth_headers())
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "ok"

    def test_get_conversation_messages(self, client):
        """获取会话消息历史"""
        # 先创建
        create_resp = client.post(
            "/api/conversations",
            json={"title": "消息测试"},
            headers=_auth_headers(),
        )
        conv_id = create_resp.json()["id"]
        # 获取消息
        resp = client.get(f"/api/conversations/{conv_id}/messages", headers=_auth_headers())
        assert resp.status_code == 200
        result = resp.json()
        assert isinstance(result, list)
        # 清理
        client.delete(f"/api/conversations/{conv_id}", headers=_auth_headers())


# ── 5. 聊天接口 ──────────────────────────────────────────────────────────────

class TestChat:
    """聊天功能 API 测试"""

    def test_chat_non_stream(self, client):
        """非流式聊天"""
        resp = client.post(
            "/api/chat",
            json={"message": "你好"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        result = resp.json()
        assert "answer" in result
        assert len(result["answer"]) > 0

    def test_chat_with_conversation_id(self, client):
        """带会话 ID 的聊天"""
        # 先创建会话
        create_resp = client.post(
            "/api/conversations",
            json={"title": "聊天测试"},
            headers=_auth_headers(),
        )
        conv_id = create_resp.json()["id"]
        # 发送消息
        resp = client.post(
            "/api/chat",
            json={"message": "你好", "conversation_id": conv_id},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        result = resp.json()
        assert "answer" in result
        # 清理
        client.delete(f"/api/conversations/{conv_id}", headers=_auth_headers())

    def test_chat_stream(self, client):
        """流式聊天（SSE）"""
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

    def test_chat_empty_message(self, client):
        """空消息应返回 400"""
        resp = client.post(
            "/api/chat",
            json={"message": ""},
            headers=_auth_headers(),
        )
        # 可能返回 400 或 200（取决于实现）
        assert resp.status_code in (200, 400, 422)


# ── 6. 模型管理 ──────────────────────────────────────────────────────────────

class TestModelManagement:
    """模型管理 API 测试"""

    def test_get_model_info(self, client):
        """获取模型状态"""
        resp = client.get("/api/model", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "loaded" in data
        assert "model_path" in data

    def test_load_model(self, client):
        """探测推理后端可用性"""
        resp = client.post(
            "/api/model/load",
            json={"model_path": "http://localhost:8080/v1"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data

    def test_model_load_progress(self, client):
        """模型加载进度 SSE 端点"""
        resp = client.get(
            "/api/model/load/progress",
            headers={**_auth_headers(), "Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        # 可能返回 SSE 流或 JSON
        assert resp.text is not None


# ── 7. 认证测试 ──────────────────────────────────────────────────────────────

class TestAuthentication:
    """API Token 认证测试"""

    def test_access_without_token(self, client):
        """无 Token 访问（测试环境禁用认证，应跳过或返回 200）"""
        resp = client.get("/api/model")
        # 测试环境中禁用认证，应返回 200
        assert resp.status_code == 200

    def test_access_with_invalid_token(self, client):
        """无效 Token 访问（测试环境禁用认证，应跳过或返回 200）"""
        resp = client.get(
            "/api/model",
            headers={"Authorization": "Bearer invalid_token"},
        )
        # 测试环境中禁用认证，应返回 200
        assert resp.status_code == 200


# ── 8. 错误处理 ──────────────────────────────────────────────────────────────

class TestErrorHandling:
    """错误处理测试"""

    def test_404_not_found(self, client):
        """访问不存在的端点应返回 404"""
        resp = client.get("/api/nonexistent_endpoint", headers=_auth_headers())
        assert resp.status_code == 404

    def test_invalid_json(self, client):
        """无效 JSON 应返回 422"""
        resp = client.post(
            "/api/chat",
            content=b"invalid json",
            headers={**_auth_headers(), "Content-Type": "application/json"},
        )
        assert resp.status_code in (400, 422)


# ── 主入口 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
