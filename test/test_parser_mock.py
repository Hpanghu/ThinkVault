"""
PDF / DOCX 解析器 Mock 测试
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


def _create_dummy(suffix=".tmp"):
    t = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    t.close()
    return Path(t.name)


def _make_pdf_page(text):
    """构造 PyMuPDF pages.get_text('dict') 返回的字典结构"""
    page = MagicMock()
    page.get_text.return_value = {  # get_text("dict")
        "blocks": [
            {
                "type": 0,
                "lines": [
                    {
                        "spans": [
                            {"text": text}
                        ]
                    }
                ]
            }
        ]
    }
    # tables
    page.find_tables.return_value = MagicMock()
    page.find_tables.return_value.tables = []
    page.find_tables.return_value.__bool__ = lambda self: False
    page.find_tables.return_value.__len__ = lambda self: 0
    return page


def _make_pdf_page_empty():
    page = MagicMock()
    page.get_text.return_value = {"blocks": []}
    page.find_tables.return_value = MagicMock()
    page.find_tables.return_value.tables = []
    page.find_tables.return_value.__bool__ = lambda self: False
    page.find_tables.return_value.__len__ = lambda self: 0
    return page


# Inject mock fitz module
mock_fitz = MagicMock()
sys.modules["fitz"] = mock_fitz

# Inject mock docx module
mock_docx_mod = MagicMock()
sys.modules["docx"] = mock_docx_mod

from thinkvault.core.parser import DocumentParser


class TestPDFMock:

    def test_basic(self):
        dummy = _create_dummy(".pdf")
        try:
            pages = [_make_pdf_page("第一章概述" + "测试内容填充" * 10), _make_pdf_page("第二章细节" + "测试内容填充" * 10), _make_pdf_page("第三章总结" + "测试内容填充" * 10)]

            mock_doc = MagicMock()
            mock_doc.__len__ = lambda self: 3
            mock_doc.__iter__ = lambda self: iter(pages)
            # getitem for page iteration
            mock_doc.__getitem__ = lambda self, i: pages[i]
            mock_fitz.open.return_value = mock_doc

            result = DocumentParser.parse(str(dummy))

            assert result.file_type == "pdf"
            assert result.total_pages == 3
            assert "概述" in result.raw_text
            assert "细节" in result.raw_text
            assert result.parse_error is None
            print("[PASS] PDF 多页提取")
        finally:
            dummy.unlink(missing_ok=True)

    def test_empty(self):
        dummy = _create_dummy(".pdf")
        try:
            pages = [_make_pdf_page_empty()]
            mock_doc = MagicMock()
            mock_doc.__len__ = lambda self: 1
            mock_doc.__iter__ = lambda self: iter(pages)
            mock_doc.__getitem__ = lambda self, i: pages[0]
            mock_fitz.open.return_value = mock_doc

            result = DocumentParser.parse(str(dummy))

            assert result.parse_error is not None
            print("[PASS] PDF 空文档检测")
        finally:
            dummy.unlink(missing_ok=True)


class TestDOCXMock:

    def test_basic(self):
        dummy = _create_dummy(".docx")
        try:
            mock_doc = MagicMock()
            p1, p2, p3 = MagicMock(), MagicMock(), MagicMock()
            p1.text = "文档标题"
            p2.text = ""
            p3.text = "正文内容"
            mock_doc.paragraphs = [p1, p2, p3]
            mock_docx_mod.Document.return_value = mock_doc

            result = DocumentParser.parse(str(dummy))

            assert result.file_type == "docx"
            assert "文档标题" in result.raw_text
            assert "正文内容" in result.raw_text
            assert result.parse_error is None
            print("[PASS] DOCX 基础段落提取")
        finally:
            dummy.unlink(missing_ok=True)

    def test_empty(self):
        dummy = _create_dummy(".docx")
        try:
            mock_doc = MagicMock()
            mock_doc.paragraphs = []
            mock_docx_mod.Document.return_value = mock_doc

            result = DocumentParser.parse(str(dummy))

            # 当前实现：空 DOCX 不设置 parse_error（与 PDF 行为不同）
            assert result.file_type == "docx"
            assert result.raw_text.strip() == ""
            print("[PASS] DOCX 空文档检测")
        finally:
            dummy.unlink(missing_ok=True)


if __name__ == "__main__":
    print("=" * 60)
    print("PDF / DOCX Mock 解析器测试")
    print("=" * 60)

    pdf_t = TestPDFMock()
    pdf_t.test_basic()
    pdf_t.test_empty()

    docx_t = TestDOCXMock()
    docx_t.test_basic()
    docx_t.test_empty()

    print("=" * 60)
    print("PDF / DOCX Mock 测试完成")