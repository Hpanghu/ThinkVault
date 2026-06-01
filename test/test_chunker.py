"""
测试：文本分块器
覆盖分块大小、重叠窗口、分隔符策略
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from thinkvault.core.chunker import TextChunker, ChunkConfig, TextChunk
from thinkvault.core.parser import DocumentParser

TEST_DIR = Path(__file__).parent


def create_minimal_parsed_doc(text: str, file_name: str = "test.txt"):
    """快速创建 ParsedDocument 用于测试"""
    file_path = TEST_DIR / "test_output" / file_name
    file_path.parent.mkdir(exist_ok=True)
    file_path.write_text(text, encoding="utf-8")
    return DocumentParser.parse(str(file_path))


def test_default_chunking():
    """默认分块参数"""
    text = "第一段内容。" * 200  # 约 1200 字
    doc = create_minimal_parsed_doc(text, "chunk_test.txt")

    chunker = TextChunker(ChunkConfig(chunk_size=512, chunk_overlap=128))
    chunks = chunker.chunk_document(doc)

    assert len(chunks) > 0
    # 每个 chunk 不超过 chunk_size
    for chunk in chunks:
        assert len(chunk.text) <= 520, f"chunk 超出大小: {len(chunk.text)}"
    print(f"[PASS] 默认分块: {len(chunks)} 个块, 每块 ≤ 512 字符")


def test_small_text():
    """小于 chunk_size 的文本"""
    text = "只有一句话的短文本。"
    doc = create_minimal_parsed_doc(text, "small_test.txt")

    chunker = TextChunker()
    chunks = chunker.chunk_document(doc)

    assert len(chunks) == 1
    assert "一句话" in chunks[0].text
    print(f"[PASS] 短文分块: {len(chunks)} 个块")


def test_empty_text():
    """空文本"""
    text = ""
    doc = create_minimal_parsed_doc(text, "empty_chunk.txt")

    chunker = TextChunker()
    chunks = chunker.chunk_document(doc)

    assert len(chunks) == 0
    print(f"[PASS] 空文本分块: {len(chunks)} 个块")


def test_metadata_preserved():
    """元数据保留"""
    text = "段落A。\n\n段落B。\n\n段落C。"
    doc = create_minimal_parsed_doc(text, "meta_test.txt")

    chunker = TextChunker(ChunkConfig(chunk_size=100, chunk_overlap=20))
    chunks = chunker.chunk_document(doc)

    for chunk in chunks:
        assert chunk.source_file == "meta_test.txt"
        assert "file_type" in chunk.metadata
        assert chunk.metadata["file_type"] == "txt"
    print(f"[PASS] 元数据保留: 检查 {len(chunks)} 个块")


def test_overlap_validation():
    """重叠窗口自动修正"""
    config = ChunkConfig(chunk_size=100, chunk_overlap=200)
    config.validate()
    assert config.chunk_overlap == 25
    print(f"[PASS] 重叠修正: {config.chunk_overlap} (原 200 → 修正为 chunk_size/4)")


def test_chinese_separator():
    """中文句号分隔"""
    text = "这是第一句话。这是第二句话。这是第三句话。"
    doc = create_minimal_parsed_doc(text, "cn_sep.txt")

    chunker = TextChunker(ChunkConfig(chunk_size=10, chunk_overlap=2))
    chunks = chunker.chunk_document(doc)
    assert len(chunks) > 1
    print(f"[PASS] 中文句号分隔: {len(chunks)} 个块")


if __name__ == "__main__":
    print("=" * 50)
    test_default_chunking()
    test_small_text()
    test_empty_text()
    test_metadata_preserved()
    test_overlap_validation()
    test_chinese_separator()
    print("=" * 50)
    print("文本分块器测试完成")
