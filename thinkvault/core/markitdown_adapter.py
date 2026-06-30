"""
MarkItDown 适配器 — 将微软 MarkItDown 的输出适配为 ThinkVault 的 ParsedDocument

设计目标：
1. 作为现有解析器的补充组件，不替换原有解析逻辑
2. 通过环境变量控制开关与适用场景，支持随时回滚
3. 保留 LLM 友好的 Markdown 结构（标题层级、列表、表格、代码块）

环境变量：
- THINKVAULT_USE_MARKITDOWN: auto | always | never (默认 auto)
    auto   - 原解析器失败/空结果时回退到 MarkItDown
    always - 优先使用 MarkItDown，失败时回退到原解析器
    never  - 完全禁用 MarkItDown（回滚用）
- THINKVAULT_MARKITDOWN_TYPES: 逗号分隔的扩展名，always 模式下仅对这些类型优先
    例如 ".pdf,.docx,.pptx"（留空表示对所有支持类型生效）
- THINKVAULT_MARKITDOWN_TIMEOUT: 单文件转换超时秒数（默认 120）
"""

import os
import threading
from pathlib import Path
from typing import Optional

from thinkvault.core.parser import ParsedDocument
from thinkvault.utils.logger import logger

# ── 可选依赖：markitdown ──
try:
    from markitdown import MarkItDown
    _markitdown_available = True
except ImportError:
    _markitdown_available = False

# MarkItDown 实例缓存（线程安全懒加载）
_md_instance: Optional["MarkItDown"] = None
_md_lock = threading.Lock()


def is_available() -> bool:
    """MarkItDown 是否可用"""
    return _markitdown_available


def _get_instance() -> Optional["MarkItDown"]:
    """懒加载 MarkItDown 单例"""
    global _md_instance
    if not _markitdown_available:
        return None
    if _md_instance is None:
        with _md_lock:
            if _md_instance is None:
                try:
                    _md_instance = MarkItDown()
                except Exception as e:
                    logger.error(f"MarkItDown 初始化失败: {e}")
                    return None
    return _md_instance


# ── 配置读取 ──────────────────────────────────────────────────

def get_mode() -> str:
    """获取 MarkItDown 使用模式: auto | always | never"""
    return os.environ.get("THINKVAULT_USE_MARKITDOWN", "auto").lower().strip()


def get_priority_types() -> set[str]:
    """获取 always 模式下优先使用 MarkItDown 的文件扩展名集合"""
    raw = os.environ.get("THINKVAULT_MARKITDOWN_TYPES", "").strip()
    if not raw:
        return set()
    return {ext.strip().lower() for ext in raw.split(",") if ext.strip()}


def get_timeout() -> int:
    """获取单文件转换超时秒数"""
    try:
        return max(10, int(os.environ.get("THINKVAULT_MARKITDOWN_TIMEOUT", "120")))
    except ValueError:
        return 120


# MarkItDown 擅长处理的扩展名（复杂公式、嵌套列表、代码块等场景）
SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".xlsm",
    ".txt", ".md", ".markdown", ".html", ".htm",
    ".csv", ".json", ".xml", ".epub", ".zip",
}


def can_handle(file_path: str) -> bool:
    """判断 MarkItDown 是否能处理该文件类型"""
    if not _markitdown_available:
        return False
    suffix = Path(file_path).suffix.lower()
    return suffix in SUPPORTED_EXTENSIONS


def should_use_as_primary(file_path: str) -> bool:
    """判断是否应优先使用 MarkItDown（always 模式 + 类型匹配）"""
    if get_mode() != "always":
        return False
    priority_types = get_priority_types()
    if not priority_types:
        return can_handle(file_path)
    suffix = Path(file_path).suffix.lower()
    return suffix in priority_types


# ── 核心转换 ──────────────────────────────────────────────────

def _markdown_to_paragraphs(markdown_text: str) -> list[dict]:
    """将 Markdown 文本拆分为段落列表，保留结构信息供 chunker 使用。

    拆分策略：按 Markdown 标题与空行分段，保留 char_count 用于页码映射。
    """
    if not markdown_text.strip():
        return []

    paragraphs = []
    # 按双换行分段，保留标题层级标记
    blocks = markdown_text.split("\n\n")
    char_offset = 0

    for block in blocks:
        text = block.strip()
        if not text:
            char_offset += len(block) + 2
            continue

        paragraphs.append({
            "text": text,
            "char_count": len(text),
            "page": 1,
            "is_markitdown": True,
        })
        char_offset += len(block) + 2

    return paragraphs


def convert(file_path: str) -> Optional[ParsedDocument]:
    """使用 MarkItDown 解析文件，返回 ParsedDocument 或 None（失败时）。

    本函数不抛异常，失败时返回 None，由调用方决定回退策略。
    """
    if not _markitdown_available:
        return None

    md = _get_instance()
    if md is None:
        return None

    path = Path(file_path)
    if not path.exists():
        return None

    try:
        result = md.convert(file_path)
        markdown_text = result.text_content or ""

        if not markdown_text.strip():
            return None

        paragraphs = _markdown_to_paragraphs(markdown_text)

        return ParsedDocument(
            file_path=file_path,
            file_name=path.name,
            file_type=path.suffix.lower().lstrip("."),
            total_pages=1,
            paragraphs=paragraphs,
            raw_text=markdown_text,
        )

    except Exception as e:
        logger.warning(f"MarkItDown 解析失败 [{file_path}]: {e}")
        return None


def convert_with_fallback(file_path: str, original_result: ParsedDocument) -> ParsedDocument:
    """混合解析策略：根据模式决定使用 MarkItDown 还是原解析结果。

    Args:
        file_path: 文件路径
        original_result: 原解析器的结果

    Returns:
        最终的 ParsedDocument（可能来自 MarkItDown 或原解析器）
    """
    mode = get_mode()

    # never 模式：完全禁用，直接返回原结果
    if mode == "never":
        return original_result

    # always 模式：优先 MarkItDown，失败回退原结果
    if mode == "always" and should_use_as_primary(file_path):
        if can_handle(file_path):
            md_result = convert(file_path)
            if md_result is not None and not md_result.is_empty:
                logger.debug(f"MarkItDown 优先解析成功: {file_path}")
                return md_result
            logger.debug(f"MarkItDown 解析失败/空，回退原解析器: {file_path}")
        return original_result

    # auto 模式：原解析器失败或空时，尝试 MarkItDown 兜底
    if mode == "auto":
        needs_fallback = (
            original_result.parse_error is not None
            or original_result.is_empty
        )
        if needs_fallback and can_handle(file_path):
            md_result = convert(file_path)
            if md_result is not None and not md_result.is_empty:
                logger.info(f"MarkItDown 兜底解析成功: {file_path}")
                return md_result
            logger.debug(f"MarkItDown 兜底也失败: {file_path}")

    return original_result
