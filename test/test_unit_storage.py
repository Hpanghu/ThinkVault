"""
单元测试：向量存储 (core/storage.py)
"""

import sys
import pytest
from unittest.mock import patch, MagicMock

from thinkvault.core.storage import VectorStore
from thinkvault.core.chunker import TextChunk


class TestVectorStoreNameEncoding:
    """知识库名称编码/解码测试"""

    def test_safe_name_basic(self):
        store = VectorStore()
        assert store._safe_name("default") == "default"
        assert store._safe_name("my kb") == "my_kb"

    def test_safe_name_with_underscore(self):
        store = VectorStore()
        assert store._safe_name("my_kb") == "my__kb"
        assert store._safe_name("test_name with space") == "test__name_with_space"

    def test_restore_name_basic(self):
        store = VectorStore()
        assert store._restore_name("default") == "default"
        assert store._restore_name("my_kb") == "my kb"

    def test_restore_name_with_double_underscore(self):
        store = VectorStore()
        assert store._restore_name("my__kb") == "my_kb"
        assert store._restore_name("test__name_with_space") == "test_name with space"

    def test_name_roundtrip(self):
        store = VectorStore()
        names = ["default", "my kb", "test_name", "kb with_underscore"]
        for name in names:
            safe = store._safe_name(name)
            restored = store._restore_name(safe)
            assert restored == name


class TestVectorStoreClient:
    """客户端管理测试"""

    def test_get_client_success(self):
        mock_chromadb = MagicMock()
        mock_client = MagicMock()
        mock_chromadb.PersistentClient.return_value = mock_client

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            store = VectorStore()
            store._client = None
            client = store._get_client()

            assert client == mock_client
            mock_chromadb.PersistentClient.assert_called_once()

    def test_get_client_failure(self):
        mock_chromadb = MagicMock()
        mock_chromadb.PersistentClient.side_effect = Exception("connection failed")

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            store = VectorStore()
            store._client = None
            client = store._get_client()

            assert client is None

    def test_get_client_cached(self):
        mock_chromadb = MagicMock()
        mock_client = MagicMock()
        mock_chromadb.PersistentClient.return_value = mock_client

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            store = VectorStore()
            store._client = None
            client1 = store._get_client()
            client2 = store._get_client()

            assert client1 == client2
            assert mock_chromadb.PersistentClient.call_count == 1


class TestVectorStoreCollection:
    """集合操作测试"""

    def test_get_or_create_collection(self):
        mock_chromadb = MagicMock()
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_collection.return_value = mock_collection
        mock_chromadb.PersistentClient.return_value = mock_client

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            store = VectorStore()
            store._client = None
            collection = store.get_or_create_collection("test_kb")

            assert collection == mock_collection
            mock_client.get_collection.assert_called_once_with(name="kb_test__kb")

    def test_get_or_create_collection_create_new(self):
        mock_chromadb = MagicMock()
        mock_client = MagicMock()
        mock_client.get_collection.side_effect = Exception("not found")
        mock_client.create_collection.return_value = MagicMock()
        mock_chromadb.PersistentClient.return_value = mock_client

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            store = VectorStore()
            store._client = None
            collection = store.get_or_create_collection("test_kb")

            assert collection is not None
            mock_client.create_collection.assert_called_once()

    def test_get_or_create_collection_client_unavailable(self):
        mock_chromadb = MagicMock()
        mock_chromadb.PersistentClient.side_effect = Exception("failed")

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            store = VectorStore()
            store._client = None
            with pytest.raises(RuntimeError):
                store.get_or_create_collection("test_kb")


class TestVectorStoreAddChunks:
    """添加文档块测试"""

    def test_add_chunks_basic(self):
        mock_chromadb = MagicMock()
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_collection.return_value = mock_collection
        mock_collection.get.return_value = {"ids": []}
        mock_chromadb.PersistentClient.return_value = mock_client

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            store = VectorStore()
            store._client = None
            chunks = [
                TextChunk(text="chunk1", chunk_index=0, source_file="test.txt"),
                TextChunk(text="chunk2", chunk_index=1, source_file="test.txt"),
            ]
            embeddings = [[0.1, 0.2], [0.3, 0.4]]

            result = store.add_chunks("test_kb", chunks, embeddings)

            assert result == 2
            mock_collection.add.assert_called_once()

    def test_add_chunks_existing_ids(self):
        mock_chromadb = MagicMock()
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_collection.return_value = mock_collection
        mock_collection.get.return_value = {"ids": ["test.txt_0"]}
        mock_chromadb.PersistentClient.return_value = mock_client

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            store = VectorStore()
            store._client = None
            chunks = [TextChunk(text="chunk1", chunk_index=0, source_file="test.txt")]
            embeddings = [[0.1, 0.2]]

            store.add_chunks("test_kb", chunks, embeddings)

            mock_collection.delete.assert_called_once()
            mock_collection.add.assert_called_once()


class TestVectorStoreSearch:
    """检索测试"""

    def test_search_success(self):
        mock_chromadb = MagicMock()
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [["id1", "id2"]],
            "documents": [["doc1", "doc2"]],
            "metadatas": [[{"source_file": "test.txt"}, {"source_file": "test.txt"}]],
            "distances": [[0.1, 0.2]],
        }
        mock_client.get_collection.return_value = mock_collection
        mock_chromadb.PersistentClient.return_value = mock_client

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            store = VectorStore()
            results = store.search("test_kb", [0.1, 0.2, 0.3], top_k=2)

            assert len(results) == 2
            assert results[0]["id"] == "id1"
            assert results[0]["text"] == "doc1"
            assert results[0]["distance"] == 0.1

    def test_search_client_unavailable(self):
        mock_chromadb = MagicMock()
        mock_chromadb.PersistentClient.side_effect = Exception("failed")

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            store = VectorStore()
            store._client = None
            results = store.search("test_kb", [0.1, 0.2, 0.3])

            assert results == []


class TestVectorStoreListAndDelete:
    """列出和删除知识库测试"""

    def test_list_knowledge_bases(self):
        mock_chromadb = MagicMock()
        mock_client = MagicMock()
        mock_coll1 = MagicMock()
        mock_coll1.name = "kb_default"
        mock_coll2 = MagicMock()
        mock_coll2.name = "kb_my_kb"
        mock_client.list_collections.return_value = [mock_coll1, mock_coll2]
        mock_chromadb.PersistentClient.return_value = mock_client

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            store = VectorStore()
            store._client = None
            kbs = store.list_knowledge_bases()

            assert len(kbs) == 2
            assert "default" in kbs
            assert "my kb" in kbs

    def test_delete_knowledge_base(self):
        mock_chromadb = MagicMock()
        mock_client = MagicMock()
        mock_chromadb.PersistentClient.return_value = mock_client

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            store = VectorStore()
            store._client = None
            store.delete_knowledge_base("test_kb")

            mock_client.delete_collection.assert_called_once_with(name="kb_test__kb")

    def test_get_chunk_count(self):
        mock_chromadb = MagicMock()
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 100
        mock_client.get_collection.return_value = mock_collection
        mock_chromadb.PersistentClient.return_value = mock_client

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            store = VectorStore()
            store._client = None
            count = store.get_chunk_count("test_kb")

            assert count == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])