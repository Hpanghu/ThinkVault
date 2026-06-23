"""
单元测试：向量化引擎 (core/embedder.py)
"""

import socket
import pytest
import os
from unittest.mock import patch

from thinkvault.core.embedder import Embedder


class TestEmbedderInit:
    """初始化测试"""

    def test_init_default(self):
        embedder = Embedder()
        assert embedder.model_name == Embedder.DEFAULT_MODEL
        assert embedder.is_loaded is False
        assert embedder.is_api_mode is False

    def test_init_custom_model(self):
        embedder = Embedder(model_name="test-model")
        assert embedder.model_name == "test-model"

    def test_init_ssrf_protection_valid_localhost(self):
        os.environ["THINKVAULT_EMBEDDING_API_URL"] = "http://localhost:8080/v1"
        embedder = Embedder()
        assert embedder.is_api_mode is True
        assert embedder._api_url == "http://localhost:8080/v1"
        del os.environ["THINKVAULT_EMBEDDING_API_URL"]

    def test_init_ssrf_protection_invalid_private_ip(self):
        os.environ["THINKVAULT_EMBEDDING_API_URL"] = "http://192.168.1.1:8080/v1"
        embedder = Embedder()
        assert embedder.is_api_mode is False
        del os.environ["THINKVAULT_EMBEDDING_API_URL"]

    def test_init_ssrf_protection_valid_external_with_mock(self):
        with patch("thinkvault.utils.security.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 80))
            ]
            os.environ["THINKVAULT_EMBEDDING_API_URL"] = "http://example.com/v1"
            embedder = Embedder()
            assert embedder.is_api_mode is True
            del os.environ["THINKVAULT_EMBEDDING_API_URL"]


class TestEmbedderProperties:
    """属性测试"""

    def test_is_loaded_api_mode(self):
        os.environ["THINKVAULT_EMBEDDING_API_URL"] = "http://localhost:8080/v1"
        embedder = Embedder()
        assert embedder.is_loaded is True
        del os.environ["THINKVAULT_EMBEDDING_API_URL"]

    def test_is_loaded_not_loaded(self):
        embedder = Embedder()
        assert embedder.is_loaded is False

    def test_is_api_mode(self):
        os.environ["THINKVAULT_EMBEDDING_API_URL"] = "http://localhost:8080/v1"
        embedder = Embedder()
        assert embedder.is_api_mode is True
        del os.environ["THINKVAULT_EMBEDDING_API_URL"]

        embedder2 = Embedder()
        assert embedder2.is_api_mode is False


class TestEmbedderCore:
    """核心功能测试"""

    @pytest.fixture
    def embedder(self):
        e = Embedder()
        yield e
        e.unload()

    def test_load(self, embedder):
        try:
            result = embedder.load()
            assert result is True
            assert embedder.is_loaded is True
        except Exception as e:
            pytest.skip(f"模型加载失败（网络/依赖问题）: {e}")

    def test_embed_batch(self, embedder):
        if not embedder.is_loaded:
            embedder.load()
        if not embedder.is_loaded:
            pytest.skip("模型未加载")
        texts = ["这是第一段文本", "这是第二段文本"]
        embeddings = embedder.embed(texts)
        assert embeddings is not None
        assert len(embeddings) == 2
        assert len(embeddings[0]) > 0

    def test_embed_single(self, embedder):
        if not embedder.is_loaded:
            embedder.load()
        if not embedder.is_loaded:
            pytest.skip("模型未加载")
        vec = embedder.embed_single("单文本测试")
        assert vec is not None
        assert len(vec) > 0

    def test_embed_empty(self, embedder):
        if not embedder.is_loaded:
            embedder.load()
        if not embedder.is_loaded:
            pytest.skip("模型未加载")
        result = embedder.embed([])
        assert result is not None
        assert len(result) == 0

    def test_embed_none(self, embedder):
        if not embedder.is_loaded:
            embedder.load()
        if not embedder.is_loaded:
            pytest.skip("模型未加载")
        result = embedder.embed(None)
        assert result is None

    def test_unload(self, embedder):
        if not embedder.is_loaded:
            embedder.load()
        if not embedder.is_loaded:
            pytest.skip("模型未加载")
        embedder.unload()
        assert embedder.is_loaded is False
        assert embedder._model is None
        assert embedder._onnx_session is None


class TestEmbedderModelPath:
    """模型路径解析测试"""

    def test_resolve_model_path_hf_format(self):
        embedder = Embedder(model_name="BAAI/bge-small-zh-v1.5")
        path = embedder._resolve_model_path()
        assert isinstance(path, str)

    def test_get_model_cache_dir_default(self):
        embedder = Embedder()
        cache_dir = embedder._get_model_cache_dir()
        assert isinstance(cache_dir, str)
        assert len(cache_dir) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])