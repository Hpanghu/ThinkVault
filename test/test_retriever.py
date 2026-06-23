"""
测试：检索引擎
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from thinkvault.core.retriever import Retriever


def test_format_context():
    """上下文格式化"""
    retriever = Retriever()
    hits = [
        {
            "text": "ThinkVault 是本地 AI 工作台",
            "metadata": {"source_file": "intro.txt", "source_page": 1},
            "distance": 0.1,
        },
        {
            "text": "支持 PDF、Word、TXT 格式",
            "metadata": {"source_file": "intro.txt", "source_page": 3},
            "distance": 0.2,
        },
    ]

    context, sources = retriever.format_context(hits)

    assert len(sources) == 2
    assert "intro.txt P1" in sources[0]
    assert "ThinkVault" in context
    assert "[来源:" in context
    print(f"[PASS] 上下文格式化: {len(sources)} 个来源")
    print(f"       来源: {sources}")


def test_format_context_empty():
    """空结果"""
    retriever = Retriever()
    context, sources = retriever.format_context([])
    assert context == ""
    assert sources == []
    print(f"[PASS] 空结果: context='{context}'")


def test_format_context_max_chars():
    """字符数限制"""
    retriever = Retriever()
    hits = [
        {
            "text": "A" * 2000,
            "metadata": {"source_file": "long.txt", "source_page": 1},
            "distance": 0.1,
        },
        {
            "text": "B" * 2000,
            "metadata": {"source_file": "long.txt", "source_page": 2},
            "distance": 0.2,
        },
    ]

    context, sources = retriever.format_context(hits, max_chars=1500)
    # 第一个 hit 的 2000 字超过 max_chars=1500，会被截断放入（total_chars==0 分支）
    # 第二个 hit 无剩余空间被跳过，最终 sources 仅含 1 个
    assert len(sources) == 1
    print(f"[PASS] 字符数限制: {len(sources)} 个来源 (max_chars=1500, 首个超限截断)")


# ── 分词测试 ──────────────────────────────────────────────────

def test_tokenize_chinese_only():
    retriever = Retriever()
    tokens = retriever._tokenize("卷积神经网络")
    # jieba 分词产生词语级别 token（如 "卷积", "神经网络"）
    assert len(tokens) > 0
    assert all(isinstance(t, str) for t in tokens)
    # jieba 应将 "卷积神经网络" 拆分为有意义的词
    assert "卷积" in tokens or "神经网络" in tokens


def test_tokenize_english_only():
    retriever = Retriever()
    tokens = retriever._tokenize("hello world")
    assert tokens == ["hello", "world"]


def test_tokenize_mixed():
    retriever = Retriever()
    tokens = retriever._tokenize("CNN卷积网络")
    # jieba 分词：cnn + 中文词
    assert "cnn" in tokens
    assert len(tokens) > 1  # 至少有中文部分


def test_tokenize_with_punctuation():
    retriever = Retriever()
    tokens = retriever._tokenize("Hello, 世界!")
    assert "hello" in tokens
    # jieba 将 "世界" 作为一个词
    assert "世界" in tokens


def test_tokenize_empty():
    retriever = Retriever()
    tokens = retriever._tokenize("")
    assert tokens == []


def test_tokenize_numbers():
    retriever = Retriever()
    tokens = retriever._tokenize("ResNet50模型")
    assert "resnet50" in tokens
    # jieba 将 "模型" 作为一个词
    assert "模型" in tokens


# ── 意图判断测试 (纯关键词路径，不依赖 embedder) ─────────────

def test_should_retrieve_keyword_doc():
    """关键词"文档"命中"""
    import os
    os.environ["THINKVAULT_DISABLE_AUTH"] = "1"
    retriever = Retriever()
    # 由于 vector_store 无数据，should_retrieve 第一阶段返回 False
    # 无法直接测试关键词命中（需要先有数据）
    # 但可以验证无数据时不崩溃
    result = retriever.should_retrieve("这个文档写了什么", "nonexistent_kb")
    assert result is False  # 知识库为空


def test_should_retrieve_empty_kb():
    retriever = Retriever()
    result = retriever.should_retrieve("什么是机器学习", "empty_kb_test")
    assert result is False


# ── 缓存失效测试 ──────────────────────────────────────────────

def test_invalidate_cache_non_existent():
    retriever = Retriever()
    # 清理不存在的知识库不崩溃
    retriever.invalidate_cache("nonexistent_kb")


def test_invalidate_cache_after_set():
    retriever = Retriever()
    retriever._bm25_cache["test_kb"] = ("mock_bm25", ["doc1"], ["id1"])
    assert "test_kb" in retriever._bm25_cache
    retriever.invalidate_cache("test_kb")
    assert "test_kb" not in retriever._bm25_cache


# ── format_context 边界 ───────────────────────────────────────

def test_format_context_second_hit_truncated():
    """第一个 hit 几乎填满 max_chars，第二个 hit 部分截断"""
    retriever = Retriever()
    hits = [
        {"text": "A" * 800, "metadata": {"source_file": "a.txt"}, "distance": 0.1},
        {"text": "B" * 800, "metadata": {"source_file": "b.txt"}, "distance": 0.2},
    ]
    context, sources = retriever.format_context(hits, max_chars=900)
    # 首个 800 字 + 前缀占用 → 第二个 hit 剩余空间不足应截断
    assert len(sources) >= 1


def test_format_context_no_metadata():
    """无 metadata 的 hit"""
    retriever = Retriever()
    hits = [{"text": "no metadata", "metadata": {}}]
    context, sources = retriever.format_context(hits)
    assert "未知" in sources[0]


if __name__ == "__main__":
    print("=" * 50)
    test_format_context()
    test_format_context_empty()
    test_format_context_max_chars()
    test_tokenize_chinese_only()
    test_tokenize_english_only()
    test_tokenize_mixed()
    test_tokenize_with_punctuation()
    test_tokenize_empty()
    test_tokenize_numbers()
    test_should_retrieve_keyword_doc()
    test_should_retrieve_empty_kb()
    test_invalidate_cache_non_existent()
    test_invalidate_cache_after_set()
    test_format_context_second_hit_truncated()
    test_format_context_no_metadata()
    print("=" * 50)
    print("检索引擎测试完成")
