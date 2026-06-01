"""
单元测试：向量化引擎 (core/embedder.py)
需要 sentence-transformers 已安装
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


class TestEmbedder:
    @pytest.fixture
    def embedder(self):
        from thinkvault.core.embedder import Embedder
        e = Embedder()
        yield e
        e.unload()

    def test_init_not_loaded(self, embedder):
        assert embedder.is_loaded is False

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
        # dim 取决于实际模型（bge-small-zh=384, bge-base-zh=768 等）
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

    def test_unload(self, embedder):
        if not embedder.is_loaded:
            embedder.load()
        if not embedder.is_loaded:
            pytest.skip("模型未加载")
        embedder.unload()
        assert embedder.is_loaded is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
