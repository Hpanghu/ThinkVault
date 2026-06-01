"""
文档解析器 — PDF / Word / PPT / Excel / TXT / Markdown
"""

import os
import re
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from thinkvault.utils.logger import logger

# DOCX 锁等待超时（秒），通过环境变量 THINKVAULT_DOCX_TIMEOUT 配置
DOCX_LOCK_TIMEOUT = int(os.environ.get("THINKVAULT_DOCX_TIMEOUT", "5"))


@dataclass
class ParsedDocument:
    """解析后的文档结构"""
    file_path: str
    file_name: str
    file_type: str       # pdf / docx / txt / md
    total_pages: int = 0
    paragraphs: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    raw_text: str = ""
    parse_error: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        return len(self.raw_text.strip()) == 0


class DocumentParser:
    """多格式文档解析器"""

    SUPPORTED_TYPES = {".pdf", ".docx", ".pptx", ".xlsx", ".xlsm", ".txt", ".md", ".markdown"}

    @classmethod
    def parse(cls, file_path: str) -> ParsedDocument:
        path = Path(file_path)
        if not path.exists():
            return ParsedDocument(
                file_path=file_path,
                file_name=path.name,
                file_type="",
                parse_error=f"文件不存在: {file_path}",
            )

        suffix = path.suffix.lower()
        if suffix not in cls.SUPPORTED_TYPES:
            return ParsedDocument(
                file_path=file_path,
                file_name=path.name,
                file_type=suffix,
                parse_error=f"不支持的文件格式: {suffix}，目前支持 {cls.SUPPORTED_TYPES}",
            )

        if suffix == ".pdf":
            return cls._parse_pdf(file_path, path)
        elif suffix == ".docx":
            return cls._parse_docx(file_path, path)
        elif suffix == ".pptx":
            return cls._parse_pptx(file_path, path)
        elif suffix in (".xlsx", ".xlsm"):
            return cls._parse_xlsx(file_path, path)
        elif suffix in (".txt",):
            return cls._parse_txt(file_path, path)
        elif suffix in (".md", ".markdown"):
            return cls._parse_markdown(file_path, path)

    @classmethod
    def _parse_pdf(cls, file_path: str, path: Path) -> ParsedDocument:
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(file_path)
            try:
                paragraphs = []
                full_text_parts = []
                table_count = 0

                for page_num, page in enumerate(doc):
                    # 提取文本块（保留段落结构）
                    blocks = page.get_text("dict")["blocks"]
                    for block in blocks:
                        if block["type"] == 0:  # 文本块
                            text = ""
                            for line in block.get("lines", []):
                                spans_text = "".join(
                                    span["text"] for span in line.get("spans", [])
                                )
                                text += spans_text
                            text = text.strip()
                            if text:
                                paragraphs.append({
                                    "page": page_num + 1,
                                    "text": text,
                                    "char_count": len(text),
                                })
                                full_text_parts.append(text)
                        elif block["type"] == 1:  # 图片块（暂不 OCR）
                            pass

                    # 提取表格
                    tables_on_page = page.find_tables()
                    if tables_on_page:
                        for tab in tables_on_page:
                            table_count += 1
                            # 提取表格内容 — 转成可搜索的文本
                            table_data = tab.extract()
                            if table_data:
                                header = table_data[0]
                                rows = table_data[1:]
                                lines = []
                                if header:
                                    lines.append(" | ".join(str(c) for c in header))
                                    lines.append(" | ".join("---" for _ in header))
                                for row in rows:
                                    lines.append(" | ".join(str(c) for c in row))
                                table_md = "\n".join(lines)
                                paragraphs.append({
                                    "page": page_num + 1,
                                    "text": table_md,
                                    "char_count": len(table_md),
                                    "is_table": True,
                                })
                                full_text_parts.append(table_md)

                total_pages = len(doc)

                raw_text = "\n\n".join(full_text_parts)

                if not raw_text.strip():
                    return ParsedDocument(
                        file_path=file_path,
                        file_name=path.name,
                        file_type="pdf",
                        total_pages=total_pages,
                        parse_error="PDF 中未检测到文字内容，可能是扫描件（纯图片PDF），需要 OCR 处理",
                    )

                return ParsedDocument(
                    file_path=file_path,
                    file_name=path.name,
                    file_type="pdf",
                    total_pages=total_pages,
                    paragraphs=paragraphs,
                    raw_text=raw_text,
                )
            finally:
                doc.close()

        except ImportError:
            return ParsedDocument(
                file_path=file_path,
                file_name=path.name,
                file_type="pdf",
                parse_error="PyMuPDF 未安装。请执行: pip install pymupdf",
            )
        except Exception as e:
            logger.error(f"PDF 解析失败: {file_path} | {e}")
            return ParsedDocument(
                file_path=file_path,
                file_name=path.name,
                file_type="pdf",
                parse_error=f"解析失败: {e}",
            )

    @classmethod
    def _parse_docx(cls, file_path: str, path: Path) -> ParsedDocument:
        try:
            from docx import Document

            # 带超时重试：Word 文档被其他程序锁定时，等待后可重试
            deadline = time.time() + DOCX_LOCK_TIMEOUT
            last_error = None
            while True:
                try:
                    doc = Document(file_path)
                    break
                except (IOError, PermissionError) as e:
                    last_error = e
                    if time.time() >= deadline:
                        return ParsedDocument(
                            file_path=file_path,
                            file_name=path.name,
                            file_type="docx",
                            parse_error=f"文件被占用，等待 {DOCX_LOCK_TIMEOUT}s 后仍无法打开: {e}",
                        )
                    time.sleep(0.5)
            paragraphs = []
            full_text_parts = []

            for i, para in enumerate(doc.paragraphs):
                text = para.text.strip()
                if text:
                    paragraphs.append({
                        "index": i,
                        "text": text,
                        "char_count": len(text),
                    })
                    full_text_parts.append(text)

            raw_text = "\n\n".join(full_text_parts)

            if not raw_text.strip():
                return ParsedDocument(
                    file_path=file_path,
                    file_name=path.name,
                    file_type="docx",
                    parse_error="DOCX 文档中未检测到文字内容，可能是空文档或纯图片文档",
                )

            return ParsedDocument(
                file_path=file_path,
                file_name=path.name,
                file_type="docx",
                paragraphs=paragraphs,
                raw_text=raw_text,
            )

        except ImportError:
            return ParsedDocument(
                file_path=file_path,
                file_name=path.name,
                file_type="docx",
                parse_error="python-docx 未安装。请执行: pip install python-docx",
            )
        except Exception as e:
            logger.error(f"DOCX 解析失败: {file_path} | {e}")
            return ParsedDocument(
                file_path=file_path,
                file_name=path.name,
                file_type="docx",
                parse_error=f"解析失败: {e}",
            )

    @classmethod
    def _parse_pptx(cls, file_path: str, path: Path) -> ParsedDocument:
        try:
            from pptx import Presentation

            prs = Presentation(file_path)
            paragraphs = []
            full_text_parts = []
            total_slides = len(prs.slides)

            for slide_num, slide in enumerate(prs.slides, start=1):
                slide_texts = []
                # 提取所有形状中的文本
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for para in shape.text_frame.paragraphs:
                            text = para.text.strip()
                            if text:
                                slide_texts.append(text)
                if slide_texts:
                    slide_content = "\n".join(slide_texts)
                    paragraphs.append({
                        "page": slide_num,
                        "text": slide_content,
                        "char_count": len(slide_content),
                    })
                    full_text_parts.append(slide_content)

                # 提取表格
                for shape in slide.shapes:
                    if shape.has_table:
                        table = shape.table
                        rows_data = []
                        for row in table.rows:
                            cells = [cell.text.strip() for cell in row.cells]
                            rows_data.append(" | ".join(cells))
                        if rows_data:
                            header = rows_data[0]
                            body = rows_data[1:]
                            lines = [header, " | ".join("---" for _ in header.split(" | "))]
                            lines.extend(body)
                            table_md = "\n".join(lines)
                            paragraphs.append({
                                "page": slide_num,
                                "text": table_md,
                                "char_count": len(table_md),
                                "is_table": True,
                            })
                            full_text_parts.append(table_md)

            raw_text = "\n\n".join(full_text_parts)

            if not raw_text.strip():
                return ParsedDocument(
                    file_path=file_path,
                    file_name=path.name,
                    file_type="pptx",
                    total_pages=total_slides,
                    parse_error="PPT 中未检测到文字内容，可能是纯图片幻灯片",
                )

            return ParsedDocument(
                file_path=file_path,
                file_name=path.name,
                file_type="pptx",
                total_pages=total_slides,
                paragraphs=paragraphs,
                raw_text=raw_text,
            )

        except ImportError:
            return ParsedDocument(
                file_path=file_path,
                file_name=path.name,
                file_type="pptx",
                parse_error="python-pptx 未安装。请执行: pip install python-pptx",
            )
        except Exception as e:
            logger.error(f"PPTX 解析失败: {file_path} | {e}")
            return ParsedDocument(
                file_path=file_path,
                file_name=path.name,
                file_type="pptx",
                parse_error=f"解析失败: {e}",
            )

    @classmethod
    def _parse_xlsx(cls, file_path: str, path: Path) -> ParsedDocument:
        try:
            import openpyxl

            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            paragraphs = []
            full_text_parts = []
            table_count = 0

            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    continue

                # 过滤全空行
                non_empty_rows = []
                for row in rows:
                    if any(cell is not None and str(cell).strip() != "" for cell in row):
                        non_empty_rows.append(row)

                if not non_empty_rows:
                    continue

                # 构建 Markdown 表格
                max_cols = max(len(row) for row in non_empty_rows)
                # 规范化每行列数
                padded_rows = []
                for row in non_empty_rows:
                    padded = list(row) + [""] * (max_cols - len(row))
                    padded_rows.append([str(c) if c is not None else "" for c in padded])

                header = padded_rows[0]
                body = padded_rows[1:]

                lines = ["## " + sheet_name, ""]
                lines.append(" | ".join(header))
                lines.append(" | ".join("---" for _ in header))
                for row in body:
                    lines.append(" | ".join(row))

                table_md = "\n".join(lines)
                table_count += 1
                paragraphs.append({
                    "page": table_count,
                    "text": table_md,
                    "char_count": len(table_md),
                    "is_table": True,
                    "sheet_name": sheet_name,
                })
                full_text_parts.append(table_md)

            wb.close()
            raw_text = "\n\n".join(full_text_parts)

            if not raw_text.strip():
                return ParsedDocument(
                    file_path=file_path,
                    file_name=path.name,
                    file_type="xlsx",
                    parse_error="Excel 文件中未检测到有效数据",
                )

            return ParsedDocument(
                file_path=file_path,
                file_name=path.name,
                file_type="xlsx",
                total_pages=table_count,
                paragraphs=paragraphs,
                raw_text=raw_text,
            )

        except ImportError:
            return ParsedDocument(
                file_path=file_path,
                file_name=path.name,
                file_type="xlsx",
                parse_error="openpyxl 未安装。请执行: pip install openpyxl",
            )
        except Exception as e:
            logger.error(f"XLSX 解析失败: {file_path} | {e}")
            return ParsedDocument(
                file_path=file_path,
                file_name=path.name,
                file_type="xlsx",
                parse_error=f"解析失败: {e}",
            )

    @classmethod
    def _parse_txt(cls, file_path: str, path: Path) -> ParsedDocument:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = path.read_text(encoding="gbk")
            except Exception:
                return ParsedDocument(
                    file_path=file_path,
                    file_name=path.name,
                    file_type="txt",
                    parse_error="无法识别文件编码，请转换为 UTF-8",
                )

        paragraphs = [
            {"index": i, "text": p.strip(), "char_count": len(p.strip())}
            for i, p in enumerate(text.split("\n\n"))
            if p.strip()
        ]

        return ParsedDocument(
            file_path=file_path,
            file_name=path.name,
            file_type="txt",
            paragraphs=paragraphs,
            raw_text=text,
        )

    @classmethod
    def _parse_markdown(cls, file_path: str, path: Path) -> ParsedDocument:
        doc = cls._parse_txt(file_path, path)
        doc.file_type = "md"
        return doc
