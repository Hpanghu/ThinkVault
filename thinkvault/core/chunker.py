"""
文本分块器 — 固定大小 + 重叠窗口
"""

import bisect
from dataclasses import dataclass, field


@dataclass
class ChunkConfig:
    chunk_size: int = 512       # 每块最大字符数
    chunk_overlap: int = 128    # 块间重叠字符数
    separators: list[str] = field(default_factory=lambda: ["\n\n", "\n", "。", ".", " "])

    def validate(self):
        if self.chunk_overlap >= self.chunk_size:
            self.chunk_overlap = max(1, self.chunk_size // 4)
        if self.chunk_overlap < 1:
            self.chunk_overlap = 1


@dataclass
class TextChunk:
    text: str
    chunk_index: int
    source_file: str
    source_page: int = 0
    metadata: dict = field(default_factory=dict)


class TextChunker:
    """基于分隔符优先 + 固定大小的智能分块"""

    def __init__(self, config: ChunkConfig = None):
        self.config = config or ChunkConfig()
        self.config.validate()

    def chunk_document(self, parsed_doc, doc_id: str = "") -> list[TextChunk]:
        """对解析后的文档进行分块，保留页面/段落元信息"""
        chunks = []
        raw_text = parsed_doc.raw_text
        if not raw_text.strip():
            return chunks

        segments = self._split_text(raw_text)

        # 如果解析器提供了段落级信息，尝试关联页码
        page_map = self._build_page_map(parsed_doc)

        chunk_index = 0
        for seg_text, seg_start in segments:
            sub_chunks = self._fixed_chunk(seg_text)
            for sub_text in sub_chunks:
                page_num = self._find_page(page_map, seg_start) if page_map else 0
                chunks.append(TextChunk(
                    text=sub_text.strip(),
                    chunk_index=chunk_index,
                    source_file=parsed_doc.file_name,
                    source_page=page_num,
                    metadata={
                        "file_path": parsed_doc.file_path,
                        "file_type": parsed_doc.file_type,
                        "doc_id": doc_id,
                    },
                ))
                chunk_index += 1

        return chunks

    def _split_text(self, text: str) -> list[tuple[str, int]]:
        """按分隔符优先级递归切分，返回 (文本段, 原文起始位置)"""
        separators = self.config.separators

        def _recursive_split(t: str, sep_idx: int, offset: int) -> list[tuple[str, int]]:
            if len(t) <= self.config.chunk_size or sep_idx >= len(separators):
                return [(t, offset)]

            sep = separators[sep_idx]
            parts = t.split(sep)

            if len(parts) == 1:
                return _recursive_split(t, sep_idx + 1, offset)

            result = []
            current_offset = offset
            for part in parts:
                part_with_sep = part + sep if sep_idx < 2 else part
                if len(part_with_sep) <= self.config.chunk_size:
                    if part_with_sep.strip():
                        result.append((part_with_sep, current_offset))
                    current_offset += len(part_with_sep)
                else:
                    result.extend(_recursive_split(part_with_sep, sep_idx + 1, current_offset))
                    current_offset += len(part_with_sep)
            return result

        return _recursive_split(text, 0, 0)

    def _fixed_chunk(self, text: str) -> list[str]:
        """固定大小切分 + 重叠"""
        if len(text) <= self.config.chunk_size:
            return [text] if text.strip() else []

        chunks = []
        start = 0
        while start < len(text):
            end = start + self.config.chunk_size
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(chunk_text)
            start += self.config.chunk_size - self.config.chunk_overlap
        return chunks

    def _build_page_map(self, parsed_doc) -> list[tuple[int, int, int]]:
        """建立文本偏移量 → 页码的间隔列表 [(start, end, page), ...]"""
        intervals = []
        if not parsed_doc.paragraphs:
            return intervals

        cumulative = 0
        for para in parsed_doc.paragraphs:
            page = para.get("page", 0)
            text_len = para.get("char_count", len(para.get("text", "")))
            if text_len > 0:
                intervals.append((cumulative, cumulative + text_len, page))
            cumulative += text_len + 2  # +2 for paragraph separator
        return intervals

    def _find_page(self, intervals: list[tuple[int, int, int]], offset: int) -> int:
        """在间隔列表中二分查找 offset 所属的页码"""
        # 构建起始位置数组用于二分
        starts = [iv[0] for iv in intervals]
        idx = bisect.bisect_right(starts, offset) - 1
        if 0 <= idx < len(intervals):
            start, end, page = intervals[idx]
            if start <= offset < end:
                return page
        return 0
