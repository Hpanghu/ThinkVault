"""
单元测试：检索引擎 (core/retriever.py)
"""

import pytest
from unittest.mock import patch, MagicMock

from thinkvault.core.retriever import Retriever


class TestRetrieverRRF:
    """RRF 分数融合测试"""

    def test_rrf_merge_empty(self):
        result = Retriever._rrf_merge([], [], top_k=5)
        assert result == []

    def test_rrf_merge_vector_only(self):
        vector_hits = [
            {"id": "doc1", "text": "text1", "metadata": {}, "distance": 0.1},
            {"id": "doc2", "text": "text2", "metadata": {}, "distance": 0.2},
        ]
        result = Retriever._rrf_merge(vector_hits, [], top_k=5)
        assert len(result) == 2
        assert result[0]["id"] == "doc1"
        assert "rrf_score" in result[0]

    def test_rrf_merge_bm25_only(self):
        bm25_hits = [
            {"id": "doc1", "text": "text1", "metadata": {}, "score": 1.0},
            {"id": "doc2", "text": "text2", "metadata": {}, "score": 0.5},
        ]
        result = Retriever._rrf_merge([], bm25_hits, top_k=5)
        assert len(result) == 2
        assert result[0]["id"] == "doc1"

    def test_rrf_merge_combined(self):
        vector_hits = [
            {"id": "doc1", "text": "text1", "metadata": {}, "distance": 0.1},
            {"id": "doc2", "text": "text2", "metadata": {}, "distance": 0.2},
        ]
        bm25_hits = [
            {"id": "doc2", "text": "text2", "metadata": {}, "score": 1.0},
            {"id": "doc3", "text": "text3", "metadata": {}, "score": 0.5},
        ]
        result = Retriever._rrf_merge(vector_hits, bm25_hits, top_k=5)
        assert len(result) == 3
        assert result[0]["id"] == "doc2"

    def test_rrf_merge_top_k_limit(self):
        vector_hits = [
            {"id": f"doc{i}", "text": f"text{i}", "metadata": {}}
            for i in range(10)
        ]
        result = Retriever._rrf_merge(vector_hits, [], top_k=3)
        assert len(result) == 3


class TestRetrieverFilters:
    """元数据过滤测试"""

    def test_build_where_clause_empty(self):
        result = Retriever._build_where_clause(None, None, None)
        assert result is None

    def test_build_where_clause_file_types(self):
        result = Retriever._build_where_clause(["pdf", "docx"], None, None)
        assert result == {"file_type": {"$in": ["pdf", "docx"]}}

    def test_build_where_clause_source_files(self):
        result = Retriever._build_where_clause(None, ["file1.txt", "file2.txt"], None)
        assert result == {"source_file": {"$in": ["file1.txt", "file2.txt"]}}

    def test_build_where_clause_tags(self):
        result = Retriever._build_where_clause(None, None, ["tag1", "tag2"])
        assert result == {"tags": {"$in": ["tag1", "tag2"]}}

    def test_build_where_clause_combined(self):
        result = Retriever._build_where_clause(
            ["pdf"], ["file1.txt"], ["tag1"]
        )
        assert result == {
            "$and": [
                {"file_type": {"$in": ["pdf"]}},
                {"source_file": {"$in": ["file1.txt"]}},
                {"tags": {"$in": ["tag1"]}},
            ]
        }

    def test_post_filter_bm25_empty(self):
        hits = [{"id": "1", "text": "test", "metadata": {}}]
        result = Retriever._post_filter_bm25(hits, None, None)
        assert len(result) == 1

    def test_post_filter_bm25_file_types(self):
        hits = [
            {"id": "1", "text": "test1", "metadata": {"file_type": "pdf"}},
            {"id": "2", "text": "test2", "metadata": {"file_type": "docx"}},
            {"id": "3", "text": "test3", "metadata": {"file_type": "txt"}},
        ]
        result = Retriever._post_filter_bm25(hits, ["pdf", "docx"], None)
        assert len(result) == 2
        assert {h["id"] for h in result} == {"1", "2"}

    def test_post_filter_bm25_source_files(self):
        hits = [
            {"id": "1", "text": "test1", "metadata": {"source_file": "a.txt"}},
            {"id": "2", "text": "test2", "metadata": {"source_file": "b.txt"}},
        ]
        result = Retriever._post_filter_bm25(hits, None, ["a.txt"])
        assert len(result) == 1
        assert result[0]["id"] == "1"


class TestRetrieverIntent:
    """意图判断测试"""

    def test_load_intent_keywords_default(self):
        import os
        original = os.environ.get("THINKVAULT_INTENT_KEYWORDS")
        if original:
            del os.environ["THINKVAULT_INTENT_KEYWORDS"]

        retriever = Retriever()
        assert len(retriever._intent_keywords) > 0
        assert "文档" in retriever._intent_keywords

        if original:
            os.environ["THINKVAULT_INTENT_KEYWORDS"] = original


class TestRetrieverCache:
    """缓存测试"""

    def test_embed_cache_ttl(self):
        retriever = Retriever()
        retriever._embed_cache_ttl = 0
        retriever._embed_cache["test"] = ([0.1, 0.2], 0)

        with patch("thinkvault.core.retriever.container") as mock_container:
            mock_container.embedder.embed_single.return_value = None
            result = retriever._get_query_embedding("test")
            assert result is None
            assert "test" not in retriever._embed_cache

    def test_embed_cache_lru(self):
        retriever = Retriever()
        retriever._embed_cache_max = 2

        with patch("thinkvault.core.retriever.container") as mock_container:
            mock_container.embedder.embed_single.return_value = [0.1]

            retriever._get_query_embedding("q1")
            retriever._get_query_embedding("q2")
            retriever._get_query_embedding("q3")

            assert "q1" not in retriever._embed_cache
            assert "q2" in retriever._embed_cache
            assert "q3" in retriever._embed_cache


if __name__ == "__main__":
    pytest.main([__file__, "-v"])