"""
Parser 覆盖率补充测试 v3 — 全量 Mock 实现

运行方式:
    cd D:/ThinkVault
    python -m pytest test/test_parser_coverage.py -v
"""

import sys
import os
import io
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import shutil
import pytest
from thinkvault.core.parser import DocumentParser, ParsedDocument


# ── 辅助：创建临时文件 ─────────────────────────────────────────────

def _tmp_file(suffix: str, content: bytes = b"") -> str:
    """创建临时文件，返回路径字符串（调用方负责 unlink）"""
    f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    if content:
        f.write(content)
    f.close()
    return f.name


# ── 1. parse() 调度器测试 ─────────────────────────────────────────────

class TestParseDispatcher:
    """测试 DocumentParser.parse() 的调度逻辑"""

    def test_file_not_found(self):
        doc = DocumentParser.parse("nonexistent_file_12345.pdf")
        assert doc.parse_error is not None
        assert "不存在" in doc.parse_error

    def test_unsupported_format(self):
        path = _tmp_file(".xyz")
        try:
            doc = DocumentParser.parse(path)
            assert doc.parse_error is not None
            assert "不支持" in doc.parse_error
        finally:
            os.unlink(path)

    def test_txt_dispatch(self):
        path = _tmp_file(".txt", "Hello World\n\nSecond paragraph.".encode("utf-8"))
        try:
            doc = DocumentParser.parse(path)
            assert doc.parse_error is None
            assert doc.file_type == "txt"
            assert len(doc.paragraphs) >= 1
            assert "Hello" in doc.raw_text
        finally:
            os.unlink(path)

    def test_md_dispatch(self):
        path = _tmp_file(".md", "# Title\n\nSome content.".encode("utf-8"))
        try:
            doc = DocumentParser.parse(path)
            assert doc.parse_error is None
            assert doc.file_type == "md"
        finally:
            os.unlink(path)


# ── 2. _parse_txt / _parse_markdown ──────────────────────────────────

class TestParseTxt:
    """TXT 解析边界情况"""

    def test_utf8(self):
        path = _tmp_file(".txt", "中文内容\n\nEnglish".encode("utf-8"))
        try:
            doc = DocumentParser.parse(path)
            assert doc.parse_error is None
            assert "中文" in doc.raw_text
        finally:
            os.unlink(path)

    def test_gbk_fallback(self):
        """GBK 编码回退"""
        path = _tmp_file(".txt")
        try:
            with open(path, "wb") as f:
                f.write("中文GBK编码".encode("gbk"))
            doc = DocumentParser.parse(path)
            assert doc.parse_error is None
            assert "中文" in doc.raw_text
        finally:
            os.unlink(path)

    def test_invalid_encoding(self):
        """无法识别的编码"""
        path = _tmp_file(".txt", b"\xff\xfe\xff\xfe")
        try:
            doc = DocumentParser.parse(path)
            assert doc.parse_error is not None
            assert "编码" in doc.parse_error
        finally:
            os.unlink(path)

    def test_empty_txt(self):
        path = _tmp_file(".txt", b"")
        try:
            doc = DocumentParser.parse(path)
            assert doc.parse_error is None
            assert doc.is_empty
        finally:
            os.unlink(path)

    def test_paragraph_split(self):
        """段落按空行分割"""
        content = "Para 1\n\nPara 2\n\nPara 3"
        path = _tmp_file(".txt", content.encode("utf-8"))
        try:
            doc = DocumentParser.parse(path)
            assert doc.parse_error is None
            assert len(doc.paragraphs) == 3
        finally:
            os.unlink(path)


# ── 3. _is_likely_scanned ─────────────────────────────────────────

class TestIsLikelyScanned:
    """扫描件判断逻辑"""

    def test_not_scanned(self):
        doc = ParsedDocument(
            file_path="test.pdf", file_name="test.pdf",
            file_type="pdf", total_pages=5,
            raw_text="A" * 500,  # 500 chars / 5 pages = 100/page
        )
        assert DocumentParser._is_likely_scanned(doc) is False

    def test_likely_scanned(self):
        doc = ParsedDocument(
            file_path="test.pdf", file_name="test.pdf",
            file_type="pdf", total_pages=5,
            raw_text="A" * 20,  # 20 chars / 5 pages = 4/page
        )
        assert DocumentParser._is_likely_scanned(doc) is True

    def test_zero_pages(self):
        doc = ParsedDocument(
            file_path="test.pdf", file_name="test.pdf",
            file_type="pdf", total_pages=0,
            raw_text="",
        )
        assert DocumentParser._is_likely_scanned(doc) is False

    def test_single_page_with_text(self):
        doc = ParsedDocument(
            file_path="test.pdf", file_name="test.pdf",
            file_type="pdf", total_pages=1,
            raw_text="A" * 200,
        )
        assert DocumentParser._is_likely_scanned(doc) is False


# ── 4. PDF 解析（Mock PyMuPDF）─────────────────────────────────

class TestParsePdfMock:
    """使用 Mock 测试 PDF 解析逻辑，无需真实 PDF"""

    def test_pymupdf_not_installed(self):
        """PyMuPDF 未安装时返回错误"""
        path = _tmp_file(".pdf", b"%PDF-1.4 fake")
        try:
            with patch.dict("sys.modules", {"fitz": None}):
                with patch("builtins.__import__", side_effect=ImportError("No module named 'fitz'")):
                    doc = DocumentParser.parse(path)
                    assert doc.parse_error is not None
                    assert "PyMuPDF" in doc.parse_error or "fitz" in doc.parse_error
        finally:
            os.unlink(path)

    def test_pdf_with_text(self):
        """模拟 PyMuPDF 返回文本"""
        mock_page = MagicMock()
        mock_page.get_text.return_value = {
            "blocks": [
                {"type": 0, "lines": [{"spans": [{"text": "第一章 概述"}]}]},
                {"type": 0, "lines": [{"spans": [{"text": "深度学习简介"}]}]},
                {"type": 1, "lines": []},  # 图片块
            ]
        }
        mock_page.find_tables.return_value = []

        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 3
        mock_doc.__iter__.return_value = [mock_page, mock_page, mock_page]
        mock_doc.__getitem__.side_effect = lambda i: mock_page

        with patch.dict("sys.modules", {"fitz": MagicMock()}):
            with patch("builtins.__import__") as mock_import:
                mock_fitz = MagicMock()
                mock_fitz.open.return_value = mock_doc
                mock_import.return_value = mock_fitz

                path = _tmp_file(".pdf")
                try:
                    doc = DocumentParser.parse(path)
                    assert doc is not None
                finally:
                    os.unlink(path)

    def test_pdf_empty_with_ocr_error(self):
        """PDF 文本为空，OCR 也不可用"""
        mock_page = MagicMock()
        mock_page.get_text.return_value = {"blocks": []}  # 空页面
        mock_page.find_tables.return_value = []

        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 1
        mock_doc.__iter__.return_value = [mock_page]
        mock_doc.__getitem__.side_effect = lambda i: mock_page

        with patch.dict("sys.modules", {"fitz": MagicMock()}):
            with patch("builtins.__import__") as mock_import:
                mock_fitz = MagicMock()
                mock_fitz.open.return_value = mock_doc
                mock_import.return_value = mock_fitz

                # Mock _ocr_pdf to return error
                ocr_error_result = ParsedDocument(
                    file_path="t.pdf", file_name="t.pdf", file_type="pdf",
                    parse_error="RapidOCR 未安装。请执行: pip install rapidocr-onnxruntime",
                )
                with patch.object(DocumentParser, "_ocr_pdf", return_value=ocr_error_result):
                    path = _tmp_file(".pdf")
                    try:
                        doc = DocumentParser.parse(path)
                        assert doc.parse_error is not None
                        assert "OCR" in doc.parse_error
                    finally:
                        os.unlink(path)

    def test_pdf_scanned_text_but_ocr_unavailable(self):
        """PDF 有少量文本（疑似扫描件），OCR不可用时返回已有文本+警告"""
        mock_page = MagicMock()
        mock_page.get_text.return_value = {
            "blocks": [
                {"type": 0, "lines": [{"spans": [{"text": "A" * 20}]}]},
            ]
        }
        mock_page.find_tables.return_value = []

        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 1
        mock_doc.__iter__.return_value = [mock_page]
        mock_doc.__getitem__.side_effect = lambda i: mock_page

        with patch.dict("sys.modules", {"fitz": MagicMock()}):
            with patch("builtins.__import__") as mock_import:
                mock_fitz = MagicMock()
                mock_fitz.open.return_value = mock_doc
                mock_import.return_value = mock_fitz

                ocr_error_result = ParsedDocument(
                    file_path="t.pdf", file_name="t.pdf", file_type="pdf",
                    parse_error="RapidOCR 未安装",
                )
                with patch.object(DocumentParser, "_ocr_pdf", return_value=ocr_error_result):
                    path = _tmp_file(".pdf")
                    try:
                        doc = DocumentParser.parse(path)
                        # 不是空文档但有少量文本，应返回文本+OCR警告
                        assert doc.parse_error is not None
                        assert "OCR" in doc.parse_error
                    finally:
                        os.unlink(path)

    def test_pdf_scanned_ocr_empty(self):
        """PDF 为扫描件，OCR 也未识别到文本"""
        mock_page = MagicMock()
        mock_page.get_text.return_value = {"blocks": []}
        mock_page.find_tables.return_value = []

        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 1
        mock_doc.__iter__.return_value = [mock_page]
        mock_doc.__getitem__.side_effect = lambda i: mock_page

        with patch.dict("sys.modules", {"fitz": MagicMock()}):
            with patch("builtins.__import__") as mock_import:
                mock_fitz = MagicMock()
                mock_fitz.open.return_value = mock_doc
                mock_import.return_value = mock_fitz

                ocr_empty_result = ParsedDocument(
                    file_path="t.pdf", file_name="t.pdf", file_type="pdf",
                    raw_text="", paragraphs=[],
                )
                with patch.object(DocumentParser, "_ocr_pdf", return_value=ocr_empty_result):
                    path = _tmp_file(".pdf")
                    try:
                        doc = DocumentParser.parse(path)
                        assert doc.parse_error is not None
                        assert "OCR" in doc.parse_error or "未检测到" in doc.parse_error
                    finally:
                        os.unlink(path)

    def test_pdf_ocr_success_merge(self):
        """PDF 少量文本 + OCR 成功 → 合并去重"""
        mock_page = MagicMock()
        mock_page.get_text.return_value = {
            "blocks": [
                {"type": 0, "lines": [{"spans": [{"text": "A" * 10}]}]},
            ]
        }
        mock_page.find_tables.return_value = []

        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 1
        mock_doc.__iter__.return_value = [mock_page]
        mock_doc.__getitem__.side_effect = lambda i: mock_page

        with patch.dict("sys.modules", {"fitz": MagicMock()}):
            with patch("builtins.__import__") as mock_import:
                mock_fitz = MagicMock()
                mock_fitz.open.return_value = mock_doc
                mock_import.return_value = mock_fitz

                ocr_success = ParsedDocument(
                    file_path="t.pdf", file_name="t.pdf", file_type="pdf",
                    raw_text="OCR识别文本",
                    paragraphs=[{"page": 1, "text": "OCR识别文本", "char_count": 6}],
                )
                with patch.object(DocumentParser, "_ocr_pdf", return_value=ocr_success):
                    path = _tmp_file(".pdf")
                    try:
                        doc = DocumentParser.parse(path)
                        # 应合并 PyMuPDF 和 OCR 结果
                        assert "OCR识别文本" in doc.raw_text
                    finally:
                        os.unlink(path)

    def test_pdf_with_tables(self):
        """PDF 包含表格"""
        mock_table = MagicMock()
        mock_table.extract.return_value = [["Name", "Age"], ["Alice", "30"], ["Bob", "25"]]

        mock_page = MagicMock()
        mock_page.get_text.return_value = {
            "blocks": [
                {"type": 0, "lines": [{"spans": [{"text": "表格标题"}]}]},
            ]
        }
        mock_page.find_tables.return_value = [mock_table]

        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 1
        mock_doc.__iter__.return_value = [mock_page]
        mock_doc.__getitem__.side_effect = lambda i: mock_page

        with patch.dict("sys.modules", {"fitz": MagicMock()}):
            with patch("builtins.__import__") as mock_import:
                mock_fitz = MagicMock()
                mock_fitz.open.return_value = mock_doc
                mock_import.return_value = mock_fitz

                path = _tmp_file(".pdf")
                try:
                    doc = DocumentParser.parse(path)
                    assert doc is not None
                    # 验证表格被提取
                    has_table = any(p.get("is_table") for p in doc.paragraphs)
                    if has_table:
                        table_paras = [p for p in doc.paragraphs if p.get("is_table")]
                        assert "Name" in table_paras[0]["text"]
                finally:
                    os.unlink(path)

    def test_pdf_general_exception(self):
        """fitz.open 抛出通用异常"""
        with patch.dict("sys.modules", {"fitz": MagicMock()}):
            with patch("builtins.__import__") as mock_import:
                mock_fitz = MagicMock()
                mock_fitz.open.side_effect = RuntimeError("PDF文件损坏")
                mock_import.return_value = mock_fitz

                path = _tmp_file(".pdf")
                try:
                    doc = DocumentParser.parse(path)
                    assert doc.parse_error is not None
                    assert "解析失败" in doc.parse_error
                finally:
                    os.unlink(path)


# ── 5. DOCX 解析（Mock python-docx）─────────────────────────────

class TestParseDocxMock:
    """使用 Mock 测试 DOCX 解析"""

    def test_docx_not_installed(self):
        """python-docx 未安装时返回错误"""
        path = _tmp_file(".docx", b"fake docx")
        try:
            with patch.dict("sys.modules", {"docx": None}):
                with patch("builtins.__import__", side_effect=ImportError("No module named 'docx'")):
                    doc = DocumentParser.parse(path)
                    assert doc.parse_error is not None
                    assert "python-docx" in doc.parse_error or "docx" in doc.parse_error
        finally:
            os.unlink(path)

    def test_docx_with_paragraphs(self):
        """模拟 DOCX 有段落"""
        path = _tmp_file(".docx")
        try:
            with patch.dict("sys.modules", {"docx": MagicMock()}):
                with patch("builtins.__import__") as mock_import:
                    mock_docx = MagicMock()
                    mock_doc = MagicMock()
                    p1, p2 = MagicMock(), MagicMock()
                    p1.text = "文档标题"
                    p2.text = "正文内容段落"
                    mock_doc.paragraphs = [p1, p2]
                    mock_docx.Document.return_value = mock_doc
                    mock_import.return_value = mock_docx

                    doc = DocumentParser.parse(path)
                    assert doc.file_type == "docx"
                    assert doc.parse_error is None
                    assert "文档标题" in doc.raw_text
                    assert "正文内容" in doc.raw_text
        finally:
            os.unlink(path)

    def test_docx_empty_content(self):
        """DOCX 所有段落文本为空"""
        path = _tmp_file(".docx")
        try:
            with patch.dict("sys.modules", {"docx": MagicMock()}):
                with patch("builtins.__import__") as mock_import:
                    mock_docx = MagicMock()
                    mock_doc = MagicMock()
                    p1, p2 = MagicMock(), MagicMock()
                    p1.text = ""
                    p2.text = "   "
                    mock_doc.paragraphs = [p1, p2]
                    mock_docx.Document.return_value = mock_doc
                    mock_import.return_value = mock_docx

                    doc = DocumentParser.parse(path)
                    assert doc.file_type == "docx"
                    assert doc.parse_error is not None
                    assert "未检测到" in doc.parse_error
        finally:
            os.unlink(path)

    def test_docx_lock_timeout(self):
        """DOCX 文件锁定超时"""
        path = _tmp_file(".docx")
        try:
            with patch.dict("sys.modules", {"docx": MagicMock()}):
                with patch("builtins.__import__") as mock_import:
                    mock_docx = MagicMock()
                    mock_docx.Document.side_effect = IOError("文件被占用")
                    mock_import.return_value = mock_docx

                    # Mock time so it exceeds DOCX_LOCK_TIMEOUT immediately
                    with patch("time.time") as mock_time:
                        mock_time.side_effect = [0.0, 10.0]  # start > deadline
                        doc = DocumentParser.parse(path)
                        assert doc.file_type == "docx"
                        assert doc.parse_error is not None
                        assert "被占用" in doc.parse_error
        finally:
            os.unlink(path)

    def test_docx_general_exception(self):
        """DOCX 解析抛出非预期异常"""
        path = _tmp_file(".docx")
        try:
            with patch.dict("sys.modules", {"docx": MagicMock()}):
                with patch("builtins.__import__") as mock_import:
                    mock_docx = MagicMock()
                    mock_docx.Document.side_effect = RuntimeError("内存不足")
                    mock_import.return_value = mock_docx

                    doc = DocumentParser.parse(path)
                    assert doc.file_type == "docx"
                    assert doc.parse_error is not None
                    assert "解析失败" in doc.parse_error
        finally:
            os.unlink(path)


# ── 6. PPTX 解析（Mock python-pptx）────────────────────────────

class TestParsePptxMock:
    """使用 Mock 测试 PPTX 解析"""

    def test_pptx_not_installed(self):
        """python-pptx 未安装时返回错误"""
        path = _tmp_file(".pptx", b"fake pptx")
        try:
            with patch.dict("sys.modules", {"pptx": None}):
                with patch("builtins.__import__", side_effect=ImportError("No module named 'pptx'")):
                    doc = DocumentParser.parse(path)
                    assert doc.parse_error is not None
                    assert "python-pptx" in doc.parse_error or "pptx" in doc.parse_error
        finally:
            os.unlink(path)

    def test_pptx_general_exception(self):
        """PPTX 解析抛出非预期异常"""
        path = _tmp_file(".pptx")
        try:
            with patch.dict("sys.modules", {"pptx": MagicMock()}):
                with patch("builtins.__import__") as mock_import:
                    mock_pptx = MagicMock()
                    mock_pptx.Presentation.side_effect = RuntimeError("文件损坏")
                    mock_import.return_value = mock_pptx

                    doc = DocumentParser.parse(path)
                    assert doc.file_type == "pptx"
                    assert doc.parse_error is not None
                    assert "解析失败" in doc.parse_error
        finally:
            os.unlink(path)


# ── 7. XLSX 解析（Mock openpyxl）─────────────────────────────

class TestParseXlsxMock:
    """使用 Mock 测试 XLSX 解析"""

    def test_openpyxl_not_installed(self):
        """openpyxl 未安装时返回错误"""
        path = _tmp_file(".xlsx", b"fake xlsx")
        try:
            with patch.dict("sys.modules", {"openpyxl": None}):
                with patch("builtins.__import__", side_effect=ImportError("No module named 'openpyxl'")):
                    doc = DocumentParser.parse(path)
                    assert doc.parse_error is not None
                    assert "openpyxl" in doc.parse_error
        finally:
            os.unlink(path)

    def test_xlsx_general_exception(self):
        """XLSX 解析抛出非预期异常"""
        path = _tmp_file(".xlsx")
        try:
            with patch.dict("sys.modules", {"openpyxl": MagicMock()}):
                with patch("builtins.__import__") as mock_import:
                    mock_oxl = MagicMock()
                    mock_oxl.load_workbook.side_effect = RuntimeError("文件损坏")
                    mock_import.return_value = mock_oxl

                    doc = DocumentParser.parse(path)
                    assert doc.file_type == "xlsx"
                    assert doc.parse_error is not None
                    assert "解析失败" in doc.parse_error
        finally:
            os.unlink(path)


# ── 8. 音频解析（Mock faster-whisper）────────────────────────────

class TestParseAudioMock:
    """使用 Mock 测试音频解析"""

    def test_whisper_not_available(self):
        """faster_whisper 未安装"""
        original = DocumentParser.SUPPORTED_TYPES
        try:
            if ".mp3" not in DocumentParser.SUPPORTED_TYPES:
                DocumentParser.SUPPORTED_TYPES = list(original) + [".mp3"]

            with patch("thinkvault.core.parser._whisper_available", False):
                path = _tmp_file(".mp3", b"fake audio")
                try:
                    doc = DocumentParser.parse(path)
                    assert doc.parse_error is not None
                    assert "faster-whisper" in doc.parse_error or "thinkvault" in doc.parse_error
                finally:
                    os.unlink(path)
        finally:
            DocumentParser.SUPPORTED_TYPES = original

    def test_audio_transcription_success(self):
        """模拟 Whisper 转录成功"""
        original = DocumentParser.SUPPORTED_TYPES
        try:
            if ".mp3" not in DocumentParser.SUPPORTED_TYPES:
                DocumentParser.SUPPORTED_TYPES = list(original) + [".mp3"]

            mock_seg1 = MagicMock()
            mock_seg1.start = 0.0
            mock_seg1.end = 15.5
            mock_seg1.text = " 这是第一段语音内容 "

            mock_seg2 = MagicMock()
            mock_seg2.start = 16.0
            mock_seg2.end = 45.0
            mock_seg2.text = " 这是第二段语音内容 "

            mock_info = MagicMock()
            mock_info.duration = 90

            mock_model = MagicMock()
            mock_model.transcribe.return_value = (iter([mock_seg1, mock_seg2]), mock_info)

            import thinkvault.core.parser as parser_mod
            parser_mod.WhisperModel = MagicMock(return_value=mock_model)

            with patch("thinkvault.core.parser._whisper_available", True):
                path = _tmp_file(".mp3", b"fake audio")
                try:
                    doc = DocumentParser.parse(path)
                    assert doc.parse_error is None
                    assert len(doc.paragraphs) == 2
                    assert "[00:00" in doc.paragraphs[0]["text"]
                    assert "[00:16" in doc.paragraphs[1]["text"]
                    assert doc.total_pages == 3
                finally:
                    os.unlink(path)
        finally:
            DocumentParser.SUPPORTED_TYPES = original

    def test_audio_transcription_empty(self):
        """Whisper 返回空结果"""
        original = DocumentParser.SUPPORTED_TYPES
        try:
            if ".wav" not in DocumentParser.SUPPORTED_TYPES:
                DocumentParser.SUPPORTED_TYPES = list(original) + [".wav"]

            mock_info = MagicMock()
            mock_info.duration = 30

            mock_model = MagicMock()
            mock_model.transcribe.return_value = (iter([]), mock_info)

            import thinkvault.core.parser as parser_mod
            parser_mod.WhisperModel = MagicMock(return_value=mock_model)

            with patch("thinkvault.core.parser._whisper_available", True):
                path = _tmp_file(".wav", b"fake audio")
                try:
                    doc = DocumentParser.parse(path)
                    assert doc.parse_error is not None
                    assert "转录结果为空" in doc.parse_error
                finally:
                    os.unlink(path)
        finally:
            DocumentParser.SUPPORTED_TYPES = original

    def test_audio_exception(self):
        """Whisper 抛出异常"""
        original = DocumentParser.SUPPORTED_TYPES
        try:
            if ".flac" not in DocumentParser.SUPPORTED_TYPES:
                DocumentParser.SUPPORTED_TYPES = list(original) + [".flac"]

            import thinkvault.core.parser as parser_mod
            parser_mod.WhisperModel = MagicMock(side_effect=RuntimeError("GPU内存不足"))

            with patch("thinkvault.core.parser._whisper_available", True):
                path = _tmp_file(".flac", b"fake audio")
                try:
                    doc = DocumentParser.parse(path)
                    assert doc.parse_error is not None
                    assert "转录" in doc.parse_error or "空" in doc.parse_error
                finally:
                    os.unlink(path)
        finally:
            DocumentParser.SUPPORTED_TYPES = original


# ── 9. 视频解析（Mock ffmpeg + faster-whisper）─────────────

class TestParseVideoMock:
    """使用 Mock 测试视频解析"""

    def test_ffmpeg_not_available(self):
        """ffmpeg 不可用时"""
        original = DocumentParser.SUPPORTED_TYPES
        try:
            if ".mp4" not in DocumentParser.SUPPORTED_TYPES:
                DocumentParser.SUPPORTED_TYPES = list(original) + [".mp4"]

            with patch("thinkvault.core.parser._ffmpeg_available", False):
                path = _tmp_file(".mp4", b"fake video")
                try:
                    doc = DocumentParser.parse(path)
                    assert doc.parse_error is not None
                    assert "ffmpeg" in doc.parse_error
                finally:
                    os.unlink(path)
        finally:
            DocumentParser.SUPPORTED_TYPES = original

    def test_video_whisper_not_available(self):
        """ffmpeg 可用但 whisper 不可用"""
        original = DocumentParser.SUPPORTED_TYPES
        try:
            if ".mp4" not in DocumentParser.SUPPORTED_TYPES:
                DocumentParser.SUPPORTED_TYPES = list(original) + [".mp4"]

            with patch("thinkvault.core.parser._ffmpeg_available", True):
                with patch("thinkvault.core.parser._whisper_available", False):
                    path = _tmp_file(".mp4", b"fake video")
                    try:
                        doc = DocumentParser.parse(path)
                        assert doc.parse_error is not None
                        assert "faster-whisper" in doc.parse_error
                    finally:
                        os.unlink(path)
        finally:
            DocumentParser.SUPPORTED_TYPES = original

    def test_video_ffmpeg_failure(self):
        """ffmpeg 提取音频失败"""
        original = DocumentParser.SUPPORTED_TYPES
        try:
            if ".mp4" not in DocumentParser.SUPPORTED_TYPES:
                DocumentParser.SUPPORTED_TYPES = list(original) + [".mp4"]

            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stderr = "ffmpeg: no such file or directory"

            with patch("thinkvault.core.parser._ffmpeg_available", True):
                with patch("thinkvault.core.parser._whisper_available", True):
                    with patch("subprocess.run", return_value=mock_result):
                        path = _tmp_file(".mp4", b"fake video")
                        try:
                            doc = DocumentParser.parse(path)
                            assert doc.parse_error is not None
                            assert "ffmpeg" in doc.parse_error
                        finally:
                            os.unlink(path)
        finally:
            DocumentParser.SUPPORTED_TYPES = original

    def test_video_timeout(self):
        """ffmpeg 超时"""
        original = DocumentParser.SUPPORTED_TYPES
        try:
            if ".avi" not in DocumentParser.SUPPORTED_TYPES:
                DocumentParser.SUPPORTED_TYPES = list(original) + [".avi"]

            with patch("thinkvault.core.parser._ffmpeg_available", True):
                with patch("thinkvault.core.parser._whisper_available", True):
                    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=300)):
                        path = _tmp_file(".avi", b"fake video")
                        try:
                            doc = DocumentParser.parse(path)
                            assert doc.parse_error is not None
                            assert "超时" in doc.parse_error
                        finally:
                            os.unlink(path)
        finally:
            DocumentParser.SUPPORTED_TYPES = original


# ── 10. ParsedDocument dataclass ─────────────────────────────────

class TestParsedDocument:
    """ParsedDocument 数据类测试"""

    def test_is_empty_true(self):
        doc = ParsedDocument(
            file_path="test.txt", file_name="test.txt",
            file_type="txt", raw_text="",
        )
        assert doc.is_empty is True

    def test_is_empty_false(self):
        doc = ParsedDocument(
            file_path="test.txt", file_name="test.txt",
            file_type="txt", raw_text="Hello",
        )
        assert doc.is_empty is False

    def test_is_empty_whitespace(self):
        doc = ParsedDocument(
            file_path="test.txt", file_name="test.txt",
            file_type="txt", raw_text="   \n  ",
        )
        assert doc.is_empty is True

    def test_fields(self):
        doc = ParsedDocument(
            file_path="test.pdf", file_name="test.pdf",
            file_type="pdf", total_pages=5,
            paragraphs=[{"page": 1, "text": "Hello", "char_count": 5}],
            raw_text="Hello",
        )
        assert doc.file_path == "test.pdf"
        assert doc.file_name == "test.pdf"
        assert doc.file_type == "pdf"
        assert doc.total_pages == 5
        assert len(doc.paragraphs) == 1
        assert doc.raw_text == "Hello"
        assert doc.parse_error is None


# ── 主入口 ─────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
