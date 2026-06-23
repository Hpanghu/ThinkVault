"""
单元测试：文本分块器 (core/chunker.py)
"""

import pytest

from thinkvault.core.chunker import TextChunker, ChunkConfig, TextChunk
from thinkvault.core.parser import ParsedDocument


class TestChunkConfig:
    """分块配置测试"""

    def test_default_config(self):
        config = ChunkConfig()
        assert config.chunk_size == 512
        assert config.chunk_overlap == 128
        assert "\n\n" in config.separators

    def test_validate_overlap_too_large(self):
        config = ChunkConfig(chunk_size=100, chunk_overlap=200)
        config.validate()
        assert config.chunk_overlap <= config.chunk_size

    def test_validate_overlap_negative(self):
        config = ChunkConfig(chunk_size=100, chunk_overlap=-10)
        config.validate()
        assert config.chunk_overlap >= 1

    def test_custom_separators(self):
        custom_sep = ["\n", "。", "."]
        config = ChunkConfig(separators=custom_sep)
        assert config.separators == custom_sep


class TestTextChunkerBasic:
    """基础分块功能测试"""

    def test_chunk_empty_document(self):
        parser_result = ParsedDocument(
            file_path="test.txt", file_name="test.txt", file_type="txt", raw_text=""
        )
        chunker = TextChunker()
        chunks = chunker.chunk_document(parser_result, doc_id="doc1")
        assert len(chunks) == 0

    def test_chunk_small_text(self):
        text = "这是一段简短的文本。"
        parser_result = ParsedDocument(
            file_path="test.txt", file_name="test.txt", file_type="txt", raw_text=text
        )
        chunker = TextChunker()
        chunks = chunker.chunk_document(parser_result, doc_id="doc1")
        assert len(chunks) == 1
        assert chunks[0].text.strip() == text.strip()
        assert chunks[0].source_file == "test.txt"
        assert chunks[0].chunk_index == 0
        assert chunks[0].metadata["doc_id"] == "doc1"

    def test_chunk_document_with_metadata(self):
        text = "测试文本内容"
        parser_result = ParsedDocument(
            file_path="/path/to/test.txt",
            file_name="test.txt",
            file_type="txt",
            raw_text=text,
        )
        chunker = TextChunker()
        chunks = chunker.chunk_document(parser_result, doc_id="doc1")
        assert len(chunks) == 1
        assert chunks[0].metadata["file_path"] == "/path/to/test.txt"
        assert chunks[0].metadata["file_type"] == "txt"


class TestTextChunkerSplitting:
    """文本切分测试"""

    def test_split_text_by_paragraph(self):
        text = "第一段文本内容非常长，超过了最大分块大小限制\n\n第二段文本内容也非常长，同样超过了最大分块大小限制\n\n第三段文本内容同样非常长，超过了最大分块大小限制"
        parser_result = ParsedDocument(
            file_path="test.txt", file_name="test.txt", file_type="txt", raw_text=text
        )
        config = ChunkConfig(chunk_size=20)
        chunker = TextChunker(config=config)
        chunks = chunker.chunk_document(parser_result, doc_id="doc1")
        assert len(chunks) >= 3

    def test_split_text_by_newline(self):
        text = "第一行\n第二行\n第三行"
        parser_result = ParsedDocument(
            file_path="test.txt", file_name="test.txt", file_type="txt", raw_text=text
        )
        chunker = TextChunker()
        chunks = chunker.chunk_document(parser_result, doc_id="doc1")
        assert len(chunks) >= 1

    def test_large_text_chunking(self):
        text = "这是一段非常长的文本" * 100
        parser_result = ParsedDocument(
            file_path="test.txt", file_name="test.txt", file_type="txt", raw_text=text
        )
        config = ChunkConfig(chunk_size=100, chunk_overlap=20)
        chunker = TextChunker(config=config)
        chunks = chunker.chunk_document(parser_result, doc_id="doc1")
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk.text) <= 100


class TestTextChunkerOverlap:
    """重叠窗口测试"""

    def test_overlap_preserved(self):
        text = "A" * 100
        parser_result = ParsedDocument(
            file_path="test.txt", file_name="test.txt", file_type="txt", raw_text=text
        )
        config = ChunkConfig(chunk_size=50, chunk_overlap=10)
        chunker = TextChunker(config=config)
        chunks = chunker.chunk_document(parser_result, doc_id="doc1")

        assert len(chunks) >= 2
        assert chunks[0].text == "A" * 50
        assert len(chunks[-1].text) <= 50

    def test_no_overlap(self):
        text = "A" * 100
        parser_result = ParsedDocument(
            file_path="test.txt", file_name="test.txt", file_type="txt", raw_text=text
        )
        config = ChunkConfig(chunk_size=50, chunk_overlap=0)
        chunker = TextChunker(config=config)
        chunks = chunker.chunk_document(parser_result, doc_id="doc1")
        assert len(chunks) >= 2


class TestTextChunkerPageMapping:
    """页码映射测试"""

    def test_build_page_map_with_paragraphs(self):
        parser_result = ParsedDocument(
            file_path="test.txt",
            file_name="test.txt",
            file_type="txt",
            raw_text="段落1\n段落2\n段落3",
            paragraphs=[
                {"text": "段落1", "page": 1, "char_count": 3},
                {"text": "段落2", "page": 2, "char_count": 3},
                {"text": "段落3", "page": 2, "char_count": 3},
            ],
        )
        chunker = TextChunker()
        chunks = chunker.chunk_document(parser_result, doc_id="doc1")
        assert len(chunks) >= 1
        assert chunks[0].source_page == 1

    def test_build_page_map_empty(self):
        parser_result = ParsedDocument(
            file_path="test.txt", file_name="test.txt", file_type="txt", raw_text="text"
        )
        chunker = TextChunker()
        chunks = chunker.chunk_document(parser_result, doc_id="doc1")
        assert chunks[0].source_page == 0


class TestTextChunk:
    """文本块结构测试"""

    def test_chunk_creation(self):
        chunk = TextChunk(
            text="测试内容",
            chunk_index=0,
            source_file="test.txt",
            source_page=5,
            metadata={"key": "value"},
        )
        assert chunk.text == "测试内容"
        assert chunk.chunk_index == 0
        assert chunk.source_file == "test.txt"
        assert chunk.source_page == 5
        assert chunk.metadata["key"] == "value"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])