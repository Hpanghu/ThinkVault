"""
单元测试：文档元数据存储 (core/document_store.py)
"""

import sys
import time
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from thinkvault.core.document_store import (
    add_document, list_documents, count_documents, get_document,
    delete_document, delete_documents_by_kb,
)
from thinkvault.core.db import SqliteStore


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """每个测试使用独立的临时数据库，避免 database is locked"""
    import thinkvault.core.document_store as ds_module
    from thinkvault.core import db as db_module

    # 创建独立的临时数据库目录
    test_db_dir = tmp_path / "thinkvault_test"
    test_db_dir.mkdir()

    # 临时替换 DB_DIR，让 SqliteStore 使用临时目录
    monkeypatch.setattr(db_module, "DB_DIR", test_db_dir)

    # 创建独立的 store 实例
    store = SqliteStore(db_name="test_documents.db")
    store.init_schema(ds_module.DOCUMENTS_SCHEMA)

    # 运行迁移
    with store.connect() as conn:
        for migration_sql in ds_module._MIGRATIONS:
            try:
                conn.execute(migration_sql)
                conn.commit()
            except Exception:
                pass

    # 替换 _instance 的内部 _store
    ds_module._instance._store = store

    yield

    # 清理
    store.close()
    ds_module._instance._store = None


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

    def test_list_documents_with_limit(self):
        for i in range(5):
            add_document(f"limit_{i}.txt", "txt", 100, "default", 1)
        docs = list_documents(knowledge_base="default", limit=2)
        assert len(docs) == 2

    def test_list_documents_with_offset(self):
        for i in range(5):
            add_document(f"offset_{i}.txt", "txt", 100, "default", 1)
        docs = list_documents(knowledge_base="default", limit=2, offset=0)
        assert len(docs) == 2
        docs2 = list_documents(knowledge_base="default", limit=2, offset=2)
        assert len(docs2) == 2
        # 两页不应有重复
        ids_page1 = {d["id"] for d in docs}
        ids_page2 = {d["id"] for d in docs2}
        assert ids_page1.isdisjoint(ids_page2)

    def test_count_documents(self):
        add_document("cnt1.txt", "txt", 100, "default", 1)
        add_document("cnt2.txt", "txt", 100, "other_kb", 1)
        total = count_documents()
        assert total >= 2
        kb_count = count_documents(knowledge_base="default")
        assert kb_count >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
