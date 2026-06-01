"""
补充测试：检索引擎 — 未覆盖分支 (BM25/向量/Cross-encoder/retrieve)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import patch, MagicMock


# ── __init__ 状态 ─────────────────────────────────────────────

def test_init_state():
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    assert isinstance(r._bm25_cache, dict)
    assert len(r._bm25_cache) == 0
    assert r._cross_encoder is None


# ── Cross-encoder ─────────────────────────────────────────────

def test_cross_encoder_import_error():
    """sentence_transformers 未安装时返回 None 且标记为 False"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch.dict("sys.modules", {"sentence_transformers": None}):
        ce = r._get_cross_encoder()
        assert ce is None
        assert r._cross_encoder is False


def test_cross_encoder_os_error():
    """OSError 时标记为 False"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    mock_ce = MagicMock()
    with patch.dict("sys.modules", {"sentence_transformers": MagicMock(), "sentence_transformers.cross_encoder": MagicMock()}):
        with patch("sentence_transformers.CrossEncoder", side_effect=OSError("download failed")):
            ce = r._get_cross_encoder()
            assert ce is None
            assert r._cross_encoder is False


def test_cross_encoder_general_exception():
    """一般异常时标记为 False"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch.dict("sys.modules", {"sentence_transformers": MagicMock(), "sentence_transformers.cross_encoder": MagicMock()}):
        with patch("sentence_transformers.CrossEncoder", side_effect=MemoryError("oom")):
            ce = r._get_cross_encoder()
            assert ce is None
            assert r._cross_encoder is False


def test_cross_encoder_cached_false():
    """已标记为 False 时直接返回 None，不重试"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    r._cross_encoder = False
    ce = r._get_cross_encoder()
    assert ce is None


def test_cross_encoder_success():
    """正常加载 CrossEncoder"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    mock_ce = MagicMock()
    with patch.dict("sys.modules", {"sentence_transformers": MagicMock(), "sentence_transformers.cross_encoder": MagicMock()}):
        with patch("sentence_transformers.CrossEncoder", return_value=mock_ce):
            ce = r._get_cross_encoder()
            assert ce is mock_ce
            # 第二次应该命中缓存
            ce2 = r._get_cross_encoder()
            assert ce2 is mock_ce


# ── BM25 ───────────────────────────────────────────────────────

def test_get_bm25_import_error():
    """rank-bm25 未安装时返回 None"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch.dict("sys.modules", {"rank_bm25": None}):
        result = r._get_bm25("test_kb")
        assert result is None
        assert "test_kb" in r._bm25_cache
        assert r._bm25_cache["test_kb"] is None


def test_bm25_search_empty():
    """_get_bm25 返回 None 时 _bm25_search 返回空"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    r._bm25_cache["test_kb"] = None
    result = r._bm25_search("hello", "test_kb", 5)
    assert result == []


def test_invalidate_cache_respects_boundary():
    """invalidate_cache 只删除指定 kb"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    r._bm25_cache["kb_a"] = ("mock", ["a"], ["1"])
    r._bm25_cache["kb_b"] = ("mock", ["b"], ["2"])
    r.invalidate_cache("kb_a")
    assert "kb_a" not in r._bm25_cache
    assert "kb_b" in r._bm25_cache


# ── 向量检索 ──────────────────────────────────────────────────

def test_vector_search_embed_fails():
    """embed_single 返回 None 时返回空"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch("thinkvault.core.retriever.container") as mock_ctr:
        mock_ctr.embedder.embed_single.return_value = None
        result = r._vector_search("query", "test_kb", 5)
        assert result == []


# ── 意图判断 ──────────────────────────────────────────────────

def test_should_retrieve_all_keyword_branches():
    """验证各类关键词能触发检索意图"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch("thinkvault.core.retriever.container") as mock_ctr:
        mock_ctr.vector_store.get_chunk_count.return_value = 100

        # 核心名词
        assert r.should_retrieve("这个文档说了什么", "test_kb") is True
        # 查找动词
        assert r.should_retrieve("帮我找一个文件", "test_kb") is True
        # 引用词
        assert r.should_retrieve("根据之前的内容", "test_kb") is True
        # 上下文指代
        assert r.should_retrieve("上面提到的那个", "test_kb") is True
        # 文件格式
        assert r.should_retrieve("我的合同PDF在哪", "test_kb") is True
        # 操作动词
        assert r.should_retrieve("帮我总结一下", "test_kb") is True
        # 疑问词
        assert r.should_retrieve("什么是深度学习", "test_kb") is True
        # 指令
        assert r.should_retrieve("请描述这个过程", "test_kb") is True
        # 英文
        assert r.should_retrieve("what is machine learning", "test_kb") is True
        assert r.should_retrieve("explain this concept", "test_kb") is True


def test_should_retrieve_no_keyword_falls_to_semantic():
    """无关键词命中时走语义兜底路径"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch("thinkvault.core.retriever.container") as mock_ctr:
        mock_ctr.vector_store.get_chunk_count.return_value = 100
        mock_ctr.embedder.is_loaded = True

        # embed_single 返回 None → 返回 False
        mock_ctr.embedder.embed_single.return_value = None
        result = r.should_retrieve("hello world", "test_kb")
        assert result is False


# ── format_context 更多边界 ────────────────────────────────────

def test_format_context_exact_fit():
    """多个 hit 精确填满 max_chars"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    hits = [
        {"text": "Short doc A", "metadata": {"source_file": "a.txt", "source_page": 1}},
        {"text": "Short doc B", "metadata": {"source_file": "b.txt", "source_page": 2}},
    ]
    context, sources = r.format_context(hits, max_chars=99999)
    assert len(sources) == 2


def test_format_context_single_hit_no_page():
    """metadata 有 source_file 但没有 source_page"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    hits = [{"text": "content", "metadata": {"source_file": "only.txt"}}]
    context, sources = r.format_context(hits)
    assert len(sources) == 1
    assert "only.txt" in sources[0]
    assert "P" not in sources[0]  # 无页码


def test_format_context_single_too_large():
    """单个片段超 max_chars 时截断放入"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    hits = [{"text": "X" * 5000, "metadata": {"source_file": "huge.txt"}}]
    context, sources = r.format_context(hits, max_chars=100)
    assert len(sources) == 1
    assert len(context) <= 120  # 允许截断标记 ...


# ── retrieve_with_rerank 兼容接口 ─────────────────────────────

def test_retrieve_with_rerank_wrapper():
    """旧接口应委托给 retrieve"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch.object(r, "retrieve", return_value=[{"id": "1", "text": "test"}]) as mock_retrieve:
        result = r.retrieve_with_rerank("query", "kb", 3, 10)
        mock_retrieve.assert_called_once_with("query", "kb", 3)
        assert result == [{"id": "1", "text": "test"}]


# ── 空检索 ────────────────────────────────────────────────────

def test_retrieve_returns_empty_when_no_hits():
    """向量和 BM25 都返回空时 retrieve 返回空"""
    from thinkvault.core.retriever import Retriever
    r = Retriever()
    with patch.object(r, "_vector_search", return_value=[]), \
         patch.object(r, "_bm25_search", return_value=[]):
        result = r.retrieve("test", "test_kb", 3)
        assert result == []


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])