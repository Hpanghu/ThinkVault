"""
MarkItDown 适配器兼容性测试

测试目标：
1. 验证 MarkItDown 适配器在 markitdown 未安装时优雅降级
2. 验证三种模式（auto/always/never）的回退策略
3. 验证 ParsedDocument 输出格式与 chunker 的兼容性
4. 验证环境变量配置的正确读取
5. 验证 Markdown → paragraphs 转换的结构完整性
"""

import os
import tempfile
import pytest

from thinkvault.core.parser import ParsedDocument
from thinkvault.core import markitdown_adapter


# ── 配置读取测试 ──────────────────────────────────────────────

class TestConfigReading:
    """环境变量配置读取测试"""

    def test_default_mode_is_auto(self, monkeypatch):
        monkeypatch.delenv("THINKVAULT_USE_MARKITDOWN", raising=False)
        assert markitdown_adapter.get_mode() == "auto"

    def test_mode_always(self, monkeypatch):
        monkeypatch.setenv("THINKVAULT_USE_MARKITDOWN", "always")
        assert markitdown_adapter.get_mode() == "always"

    def test_mode_never(self, monkeypatch):
        monkeypatch.setenv("THINKVAULT_USE_MARKITDOWN", "NEVER")
        assert markitdown_adapter.get_mode() == "never"

    def test_mode_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("THINKVAULT_USE_MARKITDOWN", "Always")
        assert markitdown_adapter.get_mode() == "always"

    def test_priority_types_empty(self, monkeypatch):
        monkeypatch.delenv("THINKVAULT_MARKITDOWN_TYPES", raising=False)
        assert markitdown_adapter.get_priority_types() == set()

    def test_priority_types_parsing(self, monkeypatch):
        monkeypatch.setenv("THINKVAULT_MARKITDOWN_TYPES", ".pdf,.docx, .pptx")
        types = markitdown_adapter.get_priority_types()
        assert ".pdf" in types
        assert ".docx" in types
        assert ".pptx" in types

    def test_timeout_default(self, monkeypatch):
        monkeypatch.delenv("THINKVAULT_MARKITDOWN_TIMEOUT", raising=False)
        assert markitdown_adapter.get_timeout() == 120

    def test_timeout_custom(self, monkeypatch):
        monkeypatch.setenv("THINKVAULT_MARKITDOWN_TIMEOUT", "60")
        assert markitdown_adapter.get_timeout() == 60

    def test_timeout_invalid_fallback(self, monkeypatch):
        monkeypatch.setenv("THINKVAULT_MARKITDOWN_TIMEOUT", "not_a_number")
        assert markitdown_adapter.get_timeout() == 120

    def test_timeout_minimum_floor(self, monkeypatch):
        monkeypatch.setenv("THINKVAULT_MARKITDOWN_TIMEOUT", "5")
        assert markitdown_adapter.get_timeout() == 10


# ── 可用性与能力判断测试 ─────────────────────────────────────

class TestAvailability:
    """MarkItDown 可用性与文件类型判断测试"""

    def test_can_handle_pdf(self):
        # 不依赖 markitdown 是否安装，测试类型判断逻辑
        if not markitdown_adapter.is_available():
            assert markitdown_adapter.can_handle("test.pdf") is False
        else:
            assert markitdown_adapter.can_handle("test.pdf") is True

    def test_can_handle_unsupported_type(self):
        assert markitdown_adapter.can_handle("test.xyz") is False

    def test_can_handle_audio_not_supported(self):
        # MarkItDown 不处理音频
        assert markitdown_adapter.can_handle("test.mp3") is False

    def test_supported_extensions_contains_common_types(self):
        assert ".pdf" in markitdown_adapter.SUPPORTED_EXTENSIONS
        assert ".docx" in markitdown_adapter.SUPPORTED_EXTENSIONS
        assert ".xlsx" in markitdown_adapter.SUPPORTED_EXTENSIONS
        assert ".html" in markitdown_adapter.SUPPORTED_EXTENSIONS


# ── 模式路由测试 ──────────────────────────────────────────────

class TestModeRouting:
    """三种模式的路由策略测试"""

    def _make_empty_result(self, file_path="test.pdf"):
        return ParsedDocument(
            file_path=file_path,
            file_name=os.path.basename(file_path),
            file_type="pdf",
            parse_error="模拟解析失败",
        )

    def _make_success_result(self, file_path="test.pdf"):
        return ParsedDocument(
            file_path=file_path,
            file_name=os.path.basename(file_path),
            file_type="pdf",
            raw_text="原始解析器成功的内容",
            paragraphs=[{"text": "原始解析器成功的内容", "char_count": 12, "page": 1}],
        )

    def test_never_mode_returns_original(self, monkeypatch):
        """never 模式：无论原结果如何，都返回原结果"""
        monkeypatch.setenv("THINKVAULT_USE_MARKITDOWN", "never")
        original = self._make_empty_result()
        result = markitdown_adapter.convert_with_fallback("test.pdf", original)
        assert result is original

    def test_never_mode_returns_original_even_on_success(self, monkeypatch):
        monkeypatch.setenv("THINKVAULT_USE_MARKITDOWN", "never")
        original = self._make_success_result()
        result = markitdown_adapter.convert_with_fallback("test.pdf", original)
        assert result is original

    def test_auto_mode_keeps_successful_original(self, monkeypatch):
        """auto 模式：原解析器成功时，不调用 MarkItDown"""
        monkeypatch.setenv("THINKVAULT_USE_MARKITDOWN", "auto")
        original = self._make_success_result()
        result = markitdown_adapter.convert_with_fallback("test.pdf", original)
        # 原结果非空无错误，应直接返回原结果
        assert result is original

    def test_auto_mode_fallback_on_error(self, monkeypatch):
        """auto 模式：原解析器失败时，尝试 MarkItDown 兜底"""
        monkeypatch.setenv("THINKVAULT_USE_MARKITDOWN", "auto")
        original = self._make_empty_result()
        # markitdown 未安装时，兜底也会失败，返回原结果
        result = markitdown_adapter.convert_with_fallback("test.pdf", original)
        # 无论 markitdown 是否可用，失败时应返回原结果
        assert result.parse_error is not None or result.is_empty is False

    def test_auto_mode_fallback_on_empty(self, monkeypatch):
        """auto 模式：原解析器返回空内容时，尝试 MarkItDown"""
        monkeypatch.setenv("THINKVAULT_USE_MARKITDOWN", "auto")
        original = ParsedDocument(
            file_path="test.pdf",
            file_name="test.pdf",
            file_type="pdf",
        )
        result = markitdown_adapter.convert_with_fallback("test.pdf", original)
        # markitdown 未安装时返回原结果（空）
        assert result is original or result.raw_text != ""

    def test_always_mode_unsupported_type_returns_original(self, monkeypatch):
        """always 模式：不支持的文件类型返回原结果"""
        monkeypatch.setenv("THINKVAULT_USE_MARKITDOWN", "always")
        original = self._make_success_result("test.xyz")
        result = markitdown_adapter.convert_with_fallback("test.xyz", original)
        assert result is original

    def test_always_mode_with_priority_types_filter(self, monkeypatch):
        """always 模式 + 指定类型过滤器：非指定类型不触发 MarkItDown"""
        monkeypatch.setenv("THINKVAULT_USE_MARKITDOWN", "always")
        monkeypatch.setenv("THINKVAULT_MARKITDOWN_TYPES", ".pdf")
        # .docx 不在优先列表中
        original = self._make_success_result("test.docx")
        result = markitdown_adapter.convert_with_fallback("test.docx", original)
        assert result is original


# ── Markdown 转 paragraphs 兼容性测试 ────────────────────────

class TestMarkdownToParagraphs:
    """验证 MarkItDown 输出的 Markdown 能正确转为 chunker 兼容的 paragraphs"""

    def test_empty_markdown(self):
        paragraphs = markitdown_adapter._markdown_to_paragraphs("")
        assert paragraphs == []

    def test_whitespace_only(self):
        paragraphs = markitdown_adapter._markdown_to_paragraphs("   \n\n  \n  ")
        assert paragraphs == []

    def test_single_paragraph(self):
        paragraphs = markitdown_adapter._markdown_to_paragraphs("简单的文本段落")
        assert len(paragraphs) == 1
        assert paragraphs[0]["text"] == "简单的文本段落"
        assert paragraphs[0]["char_count"] == 7
        assert paragraphs[0]["page"] == 1

    def test_multiple_paragraphs(self):
        md = "第一段\n\n第二段\n\n第三段"
        paragraphs = markitdown_adapter._markdown_to_paragraphs(md)
        assert len(paragraphs) == 3
        assert paragraphs[0]["text"] == "第一段"
        assert paragraphs[1]["text"] == "第二段"
        assert paragraphs[2]["text"] == "第三段"

    def test_heading_preserved(self):
        """标题层级标记应保留在 paragraph 文本中"""
        md = "# 主标题\n\n## 子标题\n\n正文内容"
        paragraphs = markitdown_adapter._markdown_to_paragraphs(md)
        assert len(paragraphs) == 3
        assert "# 主标题" in paragraphs[0]["text"]
        assert "## 子标题" in paragraphs[1]["text"]

    def test_code_block_preserved(self):
        """代码块应作为一个完整段落保留"""
        md = "说明文字\n\n```python\nprint('hello')\nprint('world')\n```\n\n后续文字"
        paragraphs = markitdown_adapter._markdown_to_paragraphs(md)
        # 代码块内的空行会导致分段，但代码内容仍在
        full_text = "\n\n".join(p["text"] for p in paragraphs)
        assert "print('hello')" in full_text
        assert "print('world')" in full_text

    def test_table_preserved(self):
        """Markdown 表格应保留结构"""
        md = "| 列1 | 列2 |\n|---|---|\n| 值1 | 值2 |"
        paragraphs = markitdown_adapter._markdown_to_paragraphs(md)
        assert len(paragraphs) >= 1
        assert "列1" in paragraphs[0]["text"]
        assert "值1" in paragraphs[0]["text"]

    def test_nested_list_preserved(self):
        """嵌套列表应保留缩进结构"""
        md = "- 一级项1\n  - 二级项1\n  - 二级项2\n- 一级项2"
        paragraphs = markitdown_adapter._markdown_to_paragraphs(md)
        full_text = paragraphs[0]["text"] if paragraphs else ""
        assert "一级项1" in full_text
        assert "二级项1" in full_text

    def test_char_count_accuracy(self):
        """char_count 应与文本实际长度一致（供 chunker 页码映射使用）"""
        md = "ABC"
        paragraphs = markitdown_adapter._markdown_to_paragraphs(md)
        assert paragraphs[0]["char_count"] == len(paragraphs[0]["text"])

    def test_is_markitdown_flag(self):
        """所有段落应带 is_markitdown 标记"""
        md = "段落1\n\n段落2"
        paragraphs = markitdown_adapter._markdown_to_paragraphs(md)
        for p in paragraphs:
            assert p.get("is_markitdown") is True


# ── convert 函数测试 ──────────────────────────────────────────

class TestConvertFunction:
    """convert 函数的输入输出测试"""

    def test_convert_nonexistent_file(self):
        result = markitdown_adapter.convert("/nonexistent/file.pdf")
        assert result is None

    def test_convert_returns_parseddocument_or_none(self):
        """convert 应返回 ParsedDocument 或 None，不抛异常"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
            f.write("测试内容")
            temp_path = f.name
        try:
            result = markitdown_adapter.convert(temp_path)
            # markitdown 未安装时返回 None，安装时返回 ParsedDocument
            assert result is None or isinstance(result, ParsedDocument)
        finally:
            os.unlink(temp_path)


# ── 与 chunker 的集成兼容性测试 ──────────────────────────────

class TestChunkerCompatibility:
    """验证 MarkItDown 适配器输出能被 TextChunker 正确消费"""

    def test_chunker_consumes_markitdown_output(self):
        """模拟 MarkItDown 输出的 ParsedDocument 应能被 chunker 分块"""
        from thinkvault.core.chunker import TextChunker, ChunkConfig

        # 模拟 MarkItDown 适配器的输出格式
        md_text = "# 标题\n\n这是第一段内容，包含足够长的文本用于分块测试。" * 20
        paragraphs = markitdown_adapter._markdown_to_paragraphs(md_text)

        parsed = ParsedDocument(
            file_path="test.md",
            file_name="test.md",
            file_type="md",
            total_pages=1,
            paragraphs=paragraphs,
            raw_text=md_text,
        )

        chunker = TextChunker(ChunkConfig(chunk_size=100, chunk_overlap=20))
        chunks = chunker.chunk_document(parsed, doc_id="test-doc")

        assert len(chunks) > 0
        assert all(c.text.strip() for c in chunks)
        assert all(c.source_file == "test.md" for c in chunks)
        assert all(c.metadata.get("file_type") == "md" for c in chunks)

    def test_chunker_page_mapping_with_markitdown(self):
        """chunker 的页码映射应能处理 MarkItDown 输出的 paragraphs"""
        from thinkvault.core.chunker import TextChunker, ChunkConfig

        md_text = "短文本段落1\n\n短文本段落2"
        paragraphs = markitdown_adapter._markdown_to_paragraphs(md_text)

        parsed = ParsedDocument(
            file_path="test.md",
            file_name="test.md",
            file_type="md",
            paragraphs=paragraphs,
            raw_text=md_text,
        )

        chunker = TextChunker(ChunkConfig(chunk_size=512, chunk_overlap=128))
        chunks = chunker.chunk_document(parsed, doc_id="test-doc")

        # 所有 chunk 的 source_page 应为有效值
        for chunk in chunks:
            assert isinstance(chunk.source_page, int)
            assert chunk.source_page >= 0


# ── 完整集成测试：parser.py 端到端 ───────────────────────────

class TestParserIntegration:
    """验证 DocumentParser.parse() 正确集成了 MarkItDown 适配器"""

    def test_parse_txt_still_works_never_mode(self, monkeypatch):
        """never 模式下，TXT 解析应与原有行为完全一致"""
        monkeypatch.setenv("THINKVAULT_USE_MARKITDOWN", "never")
        from thinkvault.core.parser import DocumentParser

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
            f.write("集成测试内容\n第二行")
            temp_path = f.name
        try:
            result = DocumentParser.parse(temp_path)
            assert result.file_type == "txt"
            assert "集成测试内容" in result.raw_text
            assert result.parse_error is None
        finally:
            os.unlink(temp_path)

    def test_parse_markdown_still_works_never_mode(self, monkeypatch):
        """never 模式下，Markdown 解析应与原有行为完全一致"""
        monkeypatch.setenv("THINKVAULT_USE_MARKITDOWN", "never")
        from thinkvault.core.parser import DocumentParser

        with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w", encoding="utf-8") as f:
            f.write("# 标题\n\n**加粗**\n\n- 列表项")
            temp_path = f.name
        try:
            result = DocumentParser.parse(temp_path)
            assert result.file_type == "md"
            assert "标题" in result.raw_text
            assert result.parse_error is None
        finally:
            os.unlink(temp_path)

    def test_parse_nonexistent_file_error_preserved(self, monkeypatch):
        """文件不存在的错误应正确传递，不被 MarkItDown 干扰"""
        monkeypatch.setenv("THINKVAULT_USE_MARKITDOWN", "always")
        from thinkvault.core.parser import DocumentParser

        result = DocumentParser.parse("/nonexistent/file.txt")
        assert "文件不存在" in result.parse_error
        assert result.is_empty is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
