"""
PPTX 解析器测试 — 使用 mock 模拟 python-pptx
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_shape_text(text):
    shape = MagicMock()
    shape.has_text_frame = True
    para = MagicMock()
    para.text = text
    shape.text_frame.paragraphs = [para]
    return shape


def _make_table(headers, rows):
    shape = MagicMock()
    shape.has_table = True
    shape.has_text_frame = False
    all_rows = [headers] + rows
    mock_rows = []
    for row_data in all_rows:
        mr = MagicMock()
        cells = [MagicMock() for _ in row_data]
        for c, t in zip(cells, row_data):
            c.text = t
        mr.cells = cells
        mock_rows.append(mr)
    shape.table.rows = mock_rows
    return shape


def _create_dummy(suffix=".pptx"):
    t = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    t.close()
    return Path(t.name)


# Inject mock pptx module before any imports from thinkvault
mock_pptx = MagicMock()
sys.modules["pptx"] = mock_pptx

from thinkvault.core.parser import DocumentParser


class TestPPTXParser:

    def test_basic_text(self):
        dummy = _create_dummy(".pptx")
        try:
            mock_prs = MagicMock()
            mock_slide = MagicMock()
            mock_prs.slides = [mock_slide]
            mock_prs.__len__ = lambda self: 1
            shapes = [_make_shape_text("幻灯片标题"), _make_shape_text("第一段正文内容")]
            mock_slide.shapes = shapes
            mock_pptx.Presentation.return_value = mock_prs

            result = DocumentParser.parse(str(dummy))

            assert result.file_type == "pptx"
            assert "幻灯片标题" in result.raw_text
            assert "第一段正文内容" in result.raw_text
            print("[PASS] PPTX 基础文本提取")
        finally:
            dummy.unlink(missing_ok=True)

    def test_with_table(self):
        dummy = _create_dummy(".pptx")
        try:
            mock_prs = MagicMock()
            mock_slide = MagicMock()
            mock_prs.slides = [mock_slide]
            mock_prs.__len__ = lambda self: 1
            shapes = [
                _make_shape_text("表格页"),
                _make_table(["名称", "数值"], [["A", "100"], ["B", "200"]]),
            ]
            mock_slide.shapes = shapes
            mock_pptx.Presentation.return_value = mock_prs

            result = DocumentParser.parse(str(dummy))

            assert "表格页" in result.raw_text
            assert "名称" in result.raw_text
            assert "100" in result.raw_text
            print("[PASS] PPTX 表格提取")
        finally:
            dummy.unlink(missing_ok=True)

    def test_multi_slide(self):
        dummy = _create_dummy(".pptx")
        try:
            mock_prs = MagicMock()
            s1, s2, s3 = MagicMock(), MagicMock(), MagicMock()
            mock_prs.slides = [s1, s2, s3]
            mock_prs.__len__ = lambda self: 3
            s1.shapes = [_make_shape_text("第一页")]
            s2.shapes = [_make_shape_text("第二页")]
            s3.shapes = [_make_shape_text("第三页")]
            mock_pptx.Presentation.return_value = mock_prs

            result = DocumentParser.parse(str(dummy))

            assert result.total_pages == 3
            assert "第二页" in result.raw_text
            print("[PASS] PPTX 多页幻灯片")
        finally:
            dummy.unlink(missing_ok=True)

    def test_empty(self):
        dummy = _create_dummy(".pptx")
        try:
            mock_prs = MagicMock()
            mock_slide = MagicMock()
            mock_prs.slides = [mock_slide]
            mock_prs.__len__ = lambda self: 1
            shape = MagicMock()
            shape.has_text_frame = False
            shape.has_table = False
            mock_slide.shapes = [shape]
            mock_pptx.Presentation.return_value = mock_prs

            result = DocumentParser.parse(str(dummy))

            assert result.parse_error is not None
            assert "未检测到文字" in result.parse_error
            print("[PASS] PPTX 空内容检测")
        finally:
            dummy.unlink(missing_ok=True)


if __name__ == "__main__":
    print("=" * 50)
    t = TestPPTXParser()
    t.test_basic_text()
    t.test_with_table()
    t.test_multi_slide()
    t.test_empty()
    print("=" * 50)
    print("PPTX 解析器测试完成")