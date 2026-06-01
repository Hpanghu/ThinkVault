"""
扩展测试：retriever.py 覆盖率从 67% → 80%+
补充遗漏路径：_get_cross_encoder 缓存命中、_get_bm25 正常路径、
_bm25_search 有结果、should_retrieve 语义兜底、retrieve 正常流程
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import numpy as np
from unittest.mock import patch, MagicMock


# ── _get_cross_encoder 缓存命中 (真值, 非 False) ─────────────

def test_cross_encoder_already_loaded():
    """已加载 CrossEncoder 实例时直接返回"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    mock_ce = MagicMock()
    r._cross_encoder = mock_ce
    result = r._get_cross_encoder()
    assert result is mock_ce


# ── _get_bm25 正常路径 ───────────────────────────────────────

def test_get_bm25_success():
    """正常构建 BM25 索引"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch("thinkvault.core.retriever.container") as mock_ctr:
        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": ["id1", "id2"],
            "documents": ["文档一 内容", "文档二 内容"],
        }
        mock_ctr.vector_store.get_or_create_collection.return_value = mock_collection

        result = r._get_bm25("test_kb")
        assert result is not None
        bm25, doc_texts, doc_ids = result
        assert doc_texts == ["文档一 内容", "文档二 内容"]
        assert doc_ids == ["id1", "id2"]


def test_get_bm25_empty_collection():
    """collection 为空时返回 None"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch("thinkvault.core.retriever.container") as mock_ctr:
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": []}
        mock_ctr.vector_store.get_or_create_collection.return_value = mock_collection

        result = r._get_bm25("empty_kb")
        assert result is None


# ── _bm25_search 有结果 ─────────────────────────────────────

def test_bm25_search_with_results():
    """BM25 检索返回匹配结果（scores > 0）"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch.object(r, "_get_bm25") as mock_get:
        mock_bm25 = MagicMock()
        mock_bm25.get_scores.return_value = np.array([0.5, 2.0, 0.0])
        mock_get.return_value = (mock_bm25, ["doc0", "doc1", "doc2"], ["id0", "id1", "id2"])

        result = r._bm25_search("test query", "test_kb", top_k=3)
        assert len(result) == 2
        assert result[0]["source"] == "bm25"
        assert result[0]["score"] == 2.0


def test_bm25_search_no_positive_scores():
    """所有 scores 为 0 时返回空"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch.object(r, "_get_bm25") as mock_get:
        mock_bm25 = MagicMock()
        mock_bm25.get_scores.return_value = np.array([0.0, 0.0])
        mock_get.return_value = (mock_bm25, ["d0", "d1"], ["i0", "i1"])

        result = r._bm25_search("xxx", "kb", 5)
        assert result == []


# ── should_retrieve 语义兜底路径 ─────────────────────────────

def test_should_retrieve_semantic_true():
    """语义相似度超过阈值返回 True"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch("thinkvault.core.retriever.container") as mock_ctr:
        mock_ctr.vector_store.get_chunk_count.return_value = 100
        mock_ctr.embedder.is_loaded = True
        emb = np.array([1.0, 0.0, 0.0])
        mock_ctr.embedder.embed_single.return_value = emb.tolist()
        mock_ctr.embedder.embed.return_value = [emb.tolist() for _ in range(3)]

        result = r.should_retrieve("xyzzy", "test_kb")
        assert result == True


def test_should_retrieve_semantic_false():
    """语义相似度低于阈值返回 False"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch("thinkvault.core.retriever.container") as mock_ctr:
        mock_ctr.vector_store.get_chunk_count.return_value = 100
        mock_ctr.embedder.is_loaded = True
        mock_ctr.embedder.embed_single.return_value = [1.0, 0.0]
        mock_ctr.embedder.embed.return_value = [[0.0, 1.0] for _ in range(3)]

        result = r.should_retrieve("unrelated", "test_kb")
        assert result == False


def test_should_retrieve_embedder_not_loaded():
    """embedder 未加载时 load 失败 → False"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch("thinkvault.core.retriever.container") as mock_ctr:
        mock_ctr.vector_store.get_chunk_count.return_value = 100
        mock_ctr.embedder.is_loaded = False
        mock_ctr.embedder.load.return_value = False

        result = r.should_retrieve("any query", "test_kb")
        assert result == False


# ── retrieve 正常流程 ────────────────────────────────────────

def test_retrieve_vector_only():
    """仅向量检索有结果，无 BM25"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch.object(r, "_vector_search", return_value=[
        {"id": "v1", "text": "vector result", "metadata": {}, "source": "vector"}
    ]), patch.object(r, "_bm25_search", return_value=[]):
        result = r.retrieve("test", "kb", 3)
        assert len(result) == 1
        assert result[0]["text"] == "vector result"


def test_retrieve_merged_and_reranked():
    """向量+BM25 合并去重 + CrossEncoder 重排序"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch.object(r, "_vector_search", return_value=[
        {"id": "chunk1", "text": "result A", "metadata": {}, "source": "vector"},
        {"id": "chunk2", "text": "result B", "metadata": {}, "source": "vector"},
    ]), patch.object(r, "_bm25_search", return_value=[
        {"id": "chunk2", "text": "result B", "metadata": {}, "source": "bm25"},
        {"id": "chunk3", "text": "result C", "metadata": {}, "source": "bm25"},
    ]), patch.object(r, "_get_cross_encoder") as mock_ce:
        mock_encoder = MagicMock()
        mock_encoder.predict.return_value = [0.8, 0.3, 0.9]
        mock_ce.return_value = mock_encoder

        result = r.retrieve("query", "kb", 2)
        assert len(result) == 2
        assert "rerank_score" in result[0]


def test_retrieve_cross_encoder_none():
    """CrossEncoder 不可用时跳过重排序"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch.object(r, "_vector_search", return_value=[
        {"id": "c1", "text": "A", "metadata": {}},
    ]), patch.object(r, "_bm25_search", return_value=[
        {"id": "c2", "text": "B", "metadata": {}},
    ]), patch.object(r, "_get_cross_encoder", return_value=None):
        result = r.retrieve("q", "kb", 5)
        assert len(result) == 2


def test_retrieve_cross_encoder_exception():
    """CrossEncoder 重排序异常时降级"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch.object(r, "_vector_search", return_value=[
        {"id": "x1", "text": "text1", "metadata": {}},
    ]), patch.object(r, "_bm25_search", return_value=[
        {"id": "x2", "text": "text2", "metadata": {}},
    ]), patch.object(r, "_get_cross_encoder") as mock_ce:
        mock_encoder = MagicMock()
        mock_encoder.predict.side_effect = RuntimeError("crash")
        mock_ce.return_value = mock_encoder

        result = r.retrieve("q", "kb", 3)
        assert len(result) == 2


# ── format_context max_chars 边界 ────────────────────────────

def test_format_context_second_hit_partial():
    """第二个 hit 有剩余空间但不足完整时截断"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    hits = [
        {"text": "A" * 500, "metadata": {"source_file": "a.txt"}, "distance": 0.1},
        {"text": "B" * 500, "metadata": {"source_file": "b.txt"}, "distance": 0.2},
    ]
    context, sources = r.format_context(hits, max_chars=600)
    assert len(sources) >= 1


# ── vector_search 有结果 ─────────────────────────────────────

def test_vector_search_with_results():
    """向量检索返回结果并标记 source"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch("thinkvault.core.retriever.container") as mock_ctr:
        mock_ctr.embedder.embed_single.return_value = [0.1, 0.2, 0.3]
        mock_ctr.vector_store.search.return_value = [
            {"id": "v1", "text": "hit1", "metadata": {}},
            {"id": "v2", "text": "hit2", "metadata": {}},
        ]
        result = r._vector_search("query", "kb", 5)
        assert len(result) == 2
        assert all(h["source"] == "vector" for h in result)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])