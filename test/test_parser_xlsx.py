"""
XLSX 解析器测试 — 使用 mock 模拟 openpyxl
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_ws(name, headers, rows):
    ws = MagicMock()
    ws.title = name

    def _iter_rows(values_only=True):
        all_rows = [tuple(headers)] + [tuple(r) for r in rows]
        for r in all_rows:
            yield r

    ws.iter_rows = _iter_rows
    return ws


def _create_dummy(suffix=".xlsx"):
    t = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    t.close()
    return Path(t.name)


# Inject mock openpyxl
mock_oxl = MagicMock()
sys.modules["openpyxl"] = mock_oxl

from thinkvault.core.parser import DocumentParser


class TestXLSXParser:

    def test_basic(self):
        dummy = _create_dummy(".xlsx")
        try:
            mock_wb = MagicMock()
            mock_wb.sheetnames = ["Sheet1"]
            ws = _make_ws("Sheet1", ["姓名", "年龄"], [["张三", "28"], ["李四", "32"]])
            mock_wb.__getitem__ = MagicMock(return_value=ws)
            mock_oxl.load_workbook.return_value = mock_wb

            result = DocumentParser.parse(str(dummy))

            assert result.file_type == "xlsx"
            assert "姓名" in result.raw_text
            assert "张三" in result.raw_text
            print("[PASS] XLSX 基础表格提取")
        finally:
            dummy.unlink(missing_ok=True)

    def test_multi_sheet(self):
        dummy = _create_dummy(".xlsx")
        try:
            mock_wb = MagicMock()
            mock_wb.sheetnames = ["一月", "二月"]
            w1 = _make_ws("一月", ["科目", "金额"], [["收入", "10000"]])
            w2 = _make_ws("二月", ["科目", "金额"], [["支出", "5000"]])
            mock_wb.__getitem__ = MagicMock(side_effect=[w1, w2])
            mock_oxl.load_workbook.return_value = mock_wb

            result = DocumentParser.parse(str(dummy))

            assert "收入" in result.raw_text
            assert "支出" in result.raw_text
            print("[PASS] XLSX 多 Sheet 提取")
        finally:
            dummy.unlink(missing_ok=True)

    def test_empty_rows_filtered(self):
        dummy = _create_dummy(".xlsx")
        try:
            mock_wb = MagicMock()
            mock_wb.sheetnames = ["Sheet1"]
            ws = MagicMock()
            ws.title = "Sheet1"

            def _iter_rows(values_only=True):
                yield ("标题", "值")
                yield ("", "")
                yield (None, None)
                yield ("数据", "123")

            ws.iter_rows = _iter_rows
            mock_wb.__getitem__ = MagicMock(return_value=ws)
            mock_oxl.load_workbook.return_value = mock_wb

            result = DocumentParser.parse(str(dummy))

            assert "数据" in result.raw_text
            assert "123" in result.raw_text
            print("[PASS] XLSX 空行过滤")
        finally:
            dummy.unlink(missing_ok=True)

    def test_empty(self):
        dummy = _create_dummy(".xlsx")
        try:
            mock_wb = MagicMock()
            mock_wb.sheetnames = ["Sheet1"]
            ws = MagicMock()
            ws.title = "Sheet1"

            def _iter_rows(values_only=True):
                yield (None, None)

            ws.iter_rows = _iter_rows
            mock_wb.__getitem__ = MagicMock(return_value=ws)
            mock_oxl.load_workbook.return_value = mock_wb

            result = DocumentParser.parse(str(dummy))

            assert result.parse_error is not None
            print("[PASS] XLSX 空数据检测")
        finally:
            dummy.unlink(missing_ok=True)


if __name__ == "__main__":
    print("=" * 50)
    t = TestXLSXParser()
    t.test_basic()
    t.test_multi_sheet()
    t.test_empty_rows_filtered()
    t.test_empty()
    print("=" * 50)
    print("XLSX 解析器测试完成")