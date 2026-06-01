"""
测试：向量存储（ChromaDB）
覆盖 知识库 CRUD、文档索引、向量检索
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from thinkvault.core.storage import VectorStore

TEST_DIR = Path(__file__).parent
TEST_DB_DIR = str(TEST_DIR / "test_output" / "test_chromadb")


def setup_store():
    """创建测试用 VectorStore"""
    store = VectorStore(db_dir=TEST_DB_DIR)
    # 清理之前的测试数据
    try:
        store.delete_knowledge_base("test_kb")
    except Exception:
        pass
    return store


def test_create_and_list():
    """创建知识库并列出"""
    store = setup_store()
    collection = store.get_or_create_collection("test_kb")
    assert collection is not None

    kbs = store.list_knowledge_bases()
    # 知识库名称存储时会做安全转换（空格→下划线），还原时下划线→空格
    assert any("test" in kb.lower() and "kb" in kb.lower() for kb in kbs), f"未找到 test_kb: {kbs}"
    print(f"[PASS] 创建知识库: {kbs}")


def test_add_and_search():
    """添加文档块并检索"""
    store = setup_store()

    # 模拟 chunks
    chunks = [
        type('Chunk', (), {
            'text': 'ThinkVault 是一个个人 AI 工作台',
            'source_file': 'intro.txt',
            'source_page': 1,
            'chunk_index': 0,
            'metadata': {'file_type': 'txt'},
        })(),
        type('Chunk', (), {
            'text': 'ChromaDB 是嵌入式向量数据库',
            'source_file': 'intro.txt',
            'source_page': 2,
            'chunk_index': 1,
            'metadata': {'file_type': 'txt'},
        })(),
    ]

    # 使用随机向量（模拟 embedding）
    import random
    random.seed(42)
    embeddings = [
        [random.random() for _ in range(384)] for _ in range(2)
    ]

    count = store.add_chunks("test_kb", chunks, embeddings)
    assert count == 2
    print(f"[PASS] 添加文档块: {count}")

    # 检索
    query_embedding = [random.random() for _ in range(384)]
    hits = store.search("test_kb", query_embedding, top_k=2)
    assert len(hits) == 2
    assert "ThinkVault" in hits[0]["text"] or "ChromaDB" in hits[0]["text"]
    print(f"[PASS] 检索: {len(hits)} 个结果, 第一个: {hits[0]['text'][:30]}...")


def test_chunk_count():
    """获取文档块数量"""
    store = setup_store()
    count = store.get_chunk_count("test_kb")
    assert count >= 0
    print(f"[PASS] 文档块数量: {count}")


def test_delete_kb():
    """删除知识库"""
    store = setup_store()
    store.get_or_create_collection("temp_kb")
    store.delete_knowledge_base("temp_kb")

    kbs = store.list_knowledge_bases()
    assert not any("temp" in kb.lower() for kb in kbs), f"temp_kb 未被删除: {kbs}"
    print(f"[PASS] 删除知识库")


def test_list_empty():
    """空数据库"""
    store = VectorStore(db_dir=str(TEST_DIR / "test_output" / "empty_db"))
    kbs = store.list_knowledge_bases()
    assert isinstance(kbs, list)
    print(f"[PASS] 空数据库: {len(kbs)} 个知识库")


if __name__ == "__main__":
    print("=" * 50)
    test_create_and_list()
    test_add_and_search()
    test_chunk_count()
    test_delete_kb()
    test_list_empty()
    print("=" * 50)
    print("向量存储测试完成")
