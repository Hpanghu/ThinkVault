"""
单元测试：文档解析器 (core/parser.py)
"""

import pytest
import tempfile
import os

from thinkvault.core.parser import DocumentParser, ParsedDocument, AUDIO_EXTENSIONS, VIDEO_EXTENSIONS


class TestParsedDocument:
    """解析后文档结构测试"""

    def test_is_empty_empty(self):
        doc = ParsedDocument(file_path="test.txt", file_name="test.txt", file_type="txt")
        assert doc.is_empty is True

    def test_is_empty_not_empty(self):
        doc = ParsedDocument(
            file_path="test.txt", file_name="test.txt", file_type="txt", raw_text="hello world"
        )
        assert doc.is_empty is False

    def test_default_values(self):
        doc = ParsedDocument(file_path="test.txt", file_name="test.txt", file_type="txt")
        assert doc.total_pages == 0
        assert doc.paragraphs == []
        assert doc.tables == []
        assert doc.parse_error is None


class TestDocumentParserBasic:
    """基础解析功能测试"""

    def test_parse_nonexistent_file(self):
        result = DocumentParser.parse("/nonexistent/path/file.txt")
        assert result.file_path == "/nonexistent/path/file.txt"
        assert result.file_name == "file.txt"
        assert result.file_type == ""
        assert "文件不存在" in result.parse_error
        assert result.is_empty is True

    def test_parse_unsupported_format(self):
        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
            f.write(b"test content")
            temp_path = f.name
        try:
            result = DocumentParser.parse(temp_path)
            assert result.file_type == ".xyz"
            assert "不支持的文件格式" in result.parse_error
        finally:
            os.unlink(temp_path)

    def test_supported_types(self):
        supported = DocumentParser.SUPPORTED_TYPES
        assert ".pdf" in supported
        assert ".docx" in supported
        assert ".txt" in supported
        assert ".md" in supported
        assert ".mp3" in supported
        assert ".mp4" in supported

    def test_audio_extensions(self):
        assert ".mp3" in AUDIO_EXTENSIONS
        assert ".wav" in AUDIO_EXTENSIONS
        assert ".m4a" in AUDIO_EXTENSIONS

    def test_video_extensions(self):
        assert ".mp4" in VIDEO_EXTENSIONS
        assert ".mkv" in VIDEO_EXTENSIONS
        assert ".avi" in VIDEO_EXTENSIONS


class TestDocumentParserTxt:
    """TXT 文件解析测试"""

    def test_parse_txt_basic(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode='w', encoding="utf-8") as f:
            f.write("第一行文本\n第二行文本\n第三行文本")
            temp_path = f.name
        try:
            result = DocumentParser.parse(temp_path)
            assert result.file_type == "txt"
            assert result.file_name == os.path.basename(temp_path)
            assert "第一行文本" in result.raw_text
            assert "第二行文本" in result.raw_text
            assert result.is_empty is False
        finally:
            os.unlink(temp_path)

    def test_parse_txt_empty(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode='w', encoding="utf-8") as f:
            f.write("")
            temp_path = f.name
        try:
            result = DocumentParser.parse(temp_path)
            assert result.file_type == "txt"
            assert result.is_empty is True
        finally:
            os.unlink(temp_path)

    def test_parse_txt_with_unicode(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode='w', encoding="utf-8") as f:
            f.write("你好世界\n测试文档\n中文内容")
            temp_path = f.name
        try:
            result = DocumentParser.parse(temp_path)
            assert "你好世界" in result.raw_text
            assert "中文内容" in result.raw_text
        finally:
            os.unlink(temp_path)


class TestDocumentParserMarkdown:
    """Markdown 文件解析测试"""

    def test_parse_markdown_basic(self):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode='w', encoding="utf-8") as f:
            f.write("# 标题\n\n## 子标题\n\n**加粗文本**\n\n- 列表项1\n- 列表项2")
            temp_path = f.name
        try:
            result = DocumentParser.parse(temp_path)
            assert result.file_type == "md"
            assert "标题" in result.raw_text
            assert "加粗文本" in result.raw_text
            assert "列表项1" in result.raw_text
        finally:
            os.unlink(temp_path)

    def test_parse_markdown_empty(self):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode='w', encoding="utf-8") as f:
            f.write("")
            temp_path = f.name
        try:
            result = DocumentParser.parse(temp_path)
            assert result.file_type == "md"
            assert result.is_empty is True
        finally:
            os.unlink(temp_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])