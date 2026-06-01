"""
单元测试：文档元数据存储 (core/document_store.py)
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from thinkvault.core.document_store import (
    add_document, list_documents, get_document,
    delete_document, delete_documents_by_kb, _store,
)
from thinkvault.core.db import SqliteStore


@pytest.fixture(autouse=True)
def cleanup():
    yield
    # 确保关闭所有连接后再删除文件
    global _store
    if _store is not None:
        _store.close()
        _store = None
    import gc
    gc.collect()
    db_path = Path.home() / ".thinkvault" / "documents.db"
    for _ in range(5):
        try:
            if db_path.exists():
                db_path.unlink()
            break
        except PermissionError:
            time.sleep(0.1)


class TestDocumentStore:
    def test_add_document(self):
        doc_id = add_document(
            file_name="test.pdf", file_type="pdf", file_size=1024,
            knowledge_base="default", chunk_count=5,
        )
        assert isinstance(doc_id, str)
        assert len(doc_id) == 16

    def test_list_documents(self):
        add_document("a.txt", "txt", 100, "default", 3)
        add_document("b.pdf", "pdf", 200, "default", 5)
        docs = list_documents()
        assert len(docs) >= 2
        titles = [d["file_name"] for d in docs]
        assert "a.txt" in titles
        assert "b.pdf" in titles

    def test_list_documents_by_kb(self):
        add_document("c.txt", "txt", 100, "kb_a", 1)
        add_document("d.txt", "txt", 100, "kb_b", 1)
        docs_a = list_documents(knowledge_base="kb_a")
        assert all(d["knowledge_base"] == "kb_a" for d in docs_a)
        assert len(docs_a) >= 1

    def test_get_document(self):
        doc_id = add_document("find_me.txt", "txt", 50, "default", 1)
        doc = get_document(doc_id)
        assert doc is not None
        assert doc["file_name"] == "find_me.txt"
        assert doc["file_type"] == "txt"
        assert doc["file_size"] == 50
        assert doc["chunk_count"] == 1
        assert doc["status"] == "indexed"

    def test_get_document_not_found(self):
        doc = get_document("nonexistent_12345")
        assert doc is None

    def test_delete_document(self):
        doc_id = add_document("del_me.txt", "txt", 50)
        result = delete_document(doc_id)
        assert result is True
        assert get_document(doc_id) is None

    def test_delete_document_not_found(self):
        result = delete_document("nonexistent")
        assert result is False

    def test_delete_documents_by_kb(self):
        add_document("e.txt", "txt", 100, "cleanup_kb", 1)
        add_document("f.txt", "txt", 100, "cleanup_kb", 1)
        count = delete_documents_by_kb("cleanup_kb")
        assert count == 2
        docs = list_documents(knowledge_base="cleanup_kb")
        assert len(docs) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
