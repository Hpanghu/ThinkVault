"""
ThinkVault V1.0 集成测试
验证完整链路: 服务启动 → 文档上传 → 聊天 → 文档列表 → 文档删除

运行方式:
    cd F:\AAone
    python -m pytest test\test_v1_integration.py -v

或直接运行:
    python test\test_v1_integration.py
"""

import sys
import os
import json
import tempfile
import time
from pathlib import Path

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from thinkvault.core.container import container


# ============================== Fixtures ==============================

@pytest.fixture(scope="module")
def client():
    """创建 TestClient，模拟 FastAPI 应用（进程内测试无需 API Token 认证）"""
    os.environ["THINKVAULT_DISABLE_AUTH"] = "1"
    from thinkvault.api.server import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def test_txt_file():
    """创建临时测试文档"""
    content = """
深度学习基础

深度学习是机器学习的一个分支，它使用多层神经网络来学习数据的层次化表示。

卷积神经网络（CNN）

CNN 是一种专门处理网格结构数据（如图像）的神经网络。核心组件包括：
1. 卷积层：通过卷积核提取局部特征
2. 池化层：降低特征图的空间维度
3. 全连接层：将提取的特征映射到最终输出

ResNet（残差网络）

ResNet 由何恺明等人于 2015 年提出，核心创新是残差连接（Residual Connection）。
通过引入跳跃连接（Skip Connection），ResNet 解决了深层网络中的梯度消失问题，
使得训练 100 层以上的深度网络成为可能。

Transformer 架构

Transformer 于 2017 年在 "Attention Is All You Need" 论文中提出。
它完全基于自注意力机制（Self-Attention），摒弃了传统的循环神经网络结构。
Transformer 已经成为现代大语言模型的基础架构。

BERT 和 GPT

BERT（Bidirectional Encoder Representations from Transformers）
使用双向 Transformer 编码器，通过掩码语言模型（MLM）进行预训练。
GPT（Generative Pre-trained Transformer）使用单向 Transformer 解码器，
通过自回归语言模型进行预训练，是 ChatGPT 等对话模型的基础。
"""
    tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.txt', encoding='utf-8', delete=False
    )
    tmp.write(content)
    tmp.close()
    yield tmp.name
    os.unlink(tmp.name)


# ============================== 测试用例 ==============================

class TestServerHealth:
    """服务健康检查"""

    def test_root_returns_webui(self, client):
        """访问根路径应返回 WebUI"""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "ThinkVault" in resp.text

    def test_hardware_info(self, client):
        """硬件检测 API 可用"""
        resp = client.get("/api/hardware")
        assert resp.status_code == 200
        data = resp.json()
        assert "cpu_count" in data
        assert "total_ram_gb" in data
        assert isinstance(data["cpu_count"], int)

    def test_model_info(self, client):
        """模型状态 API 可用"""
        resp = client.get("/api/model")
        assert resp.status_code == 200
        data = resp.json()
        assert "loaded" in data
        assert "model_path" in data


class TestDocumentUpload:
    """文档上传测试"""

    def test_upload_txt(self, client, test_txt_file):
        """上传 TXT 文档"""
        with open(test_txt_file, 'rb') as f:
            resp = client.post(
                "/api/documents/upload",
                files={"file": ("test_deep_learning.txt", f, "text/plain")},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["file_name"] == "test_deep_learning.txt"
        assert data["chunk_count"] > 0
        assert data["doc_id"] is not None

        return data["doc_id"]

    def test_upload_empty_file(self, client):
        """上传空文件应报错"""
        import io
        empty_file = io.BytesIO(b"")
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("empty.txt", empty_file, "text/plain")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"

    def test_upload_unsupported_type(self, client):
        """上传不支持的文件格式应报错"""
        import io
        fake_file = io.BytesIO(b"binary data")
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("test.exe", fake_file, "application/octet-stream")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "不支持" in data.get("error", "")

    def test_upload_preserves_knowledge_base(self, client, test_txt_file):
        """上传到指定知识库"""
        with open(test_txt_file, 'rb') as f:
            resp = client.post(
                "/api/documents/upload?knowledge_base=test_kb",
                files={"file": ("kb_test.txt", f, "text/plain")},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestDocumentList:
    """文档列表测试"""

    def test_list_documents(self, client):
        """列出已索引文档"""
        resp = client.get("/api/documents")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # 至少应有之前上传的文档
        for doc in data:
            assert "id" in doc
            assert "file_name" in doc
            assert "file_type" in doc
            assert "chunk_count" in doc

    def test_list_documents_by_kb(self, client):
        """按知识库过滤文档列表"""
        resp = client.get("/api/documents?knowledge_base=test_kb")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


class TestDeleteDocument:
    """文档删除测试"""

    def test_delete_existing(self, client):
        """删除已存在的文档"""
        # 先获取文档列表
        list_resp = client.get("/api/documents")
        docs = list_resp.json()

        if not docs:
            pytest.skip("没有可删除的文档")

        doc_id = docs[0]["id"]
        resp = client.delete(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_delete_nonexistent(self, client):
        """删除不存在的文档应返回 404"""
        resp = client.delete("/api/documents/nonexistent_id_12345")
        assert resp.status_code == 404


class TestChat:
    """聊天功能测试"""

    def test_chat_without_documents(self, client):
        """无文档时的基础对话"""
        resp = client.post(
            "/api/chat",
            json={"message": "你好，请简单介绍一下自己"},
        )
        # 模型未加载时返回 503，跳过 LLM 相关断言
        if resp.status_code == 503:
            pytest.skip("模型未加载，跳过 LLM 测试")
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data

        assert len(data["answer"]) > 0

    def test_chat_with_documents(self, client):
        """有文档时的 RAG 对话 — 需要先确保有文档已索引"""
        # 检查是否有已索引文档
        list_resp = client.get("/api/documents")
        docs = list_resp.json()

        if not docs:
            # 没有文档时先上传一个
            import io
            content = "Transformer 是一种基于自注意力机制的神经网络架构。它由 Vaswani 等人在 2017 年提出。"
            test_file = io.BytesIO(content.encode('utf-8'))
            upload_resp = client.post(
                "/api/documents/upload",
                files={"file": ("transformer_test.txt", test_file, "text/plain")},
            )
            assert upload_resp.json()["status"] == "ok"

        resp = client.post(
            "/api/chat",
            json={"message": "Transformer 是什么？"},
        )
        # 模型未加载时返回 503，跳过 LLM 相关断言
        if resp.status_code == 503:
            pytest.skip("模型未加载，跳过 LLM 测试")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["answer"]) > 0
        # 检查 stats（LLM 不可用时 stats 含 error 键而非 tokens_per_sec）
        if data.get("stats") and "error" not in data["stats"]:
            assert "tokens_per_sec" in data["stats"]
            assert "output_tokens" in data["stats"]


class TestKnowledgeBase:
    """知识库管理测试"""

    def test_list_knowledge_bases(self, client):
        """列出所有知识库"""
        resp = client.get("/api/knowledge-bases")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


class TestModelManagement:
    """模型管理测试"""

    def test_load_model_detects_backend(self, client):
        """检测推理后端可用性（当前 Ollama 运行中应返回 ok）"""
        resp = client.post(
            "/api/model/load",
            json={"model_path": "http://localhost:11434/v1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert container.thinkvault_llm.is_loaded


# ============================== 主入口 ==============================

if __name__ == "__main__":
    print("=" * 60)
    print("ThinkVault V1.0 集成测试")
    print("=" * 60)
    ret = pytest.main([__file__, "-v", "-s", "--tb=short"])
    sys.exit(ret)
