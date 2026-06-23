"""实时碎片摘要器 — 对话中的智能汇总表述"""

from typing import List, Dict, Optional

from thinkvault.utils.logger import logger


class InlineSummarizer:
    """对话中的实时汇总器

    将检索到的碎片文本实时汇总为逻辑连贯的总述性文本，
    并附参考来源，支持不同角色的开场白风格。
    """

    def __init__(self):
        pass

    def summarize_chunks(
        self,
        chunks: List[Dict],
        query: str,
        role_name: str = "知识馆长",
    ) -> str:
        """
        将检索到的碎片文本实时汇总

        Args:
            chunks: 检索到的碎片列表，每个碎片包含 text, source_file, source_page 等字段
            query: 用户查询
            role_name: 当前角色名称，用于生成角色风格的开场白

        Returns:
            汇总表述文本，包含开场白、核心内容和参考来源
        """
        if not chunks:
            return ""

        sources = self._extract_sources(chunks)
        if len(chunks) == 1:
            return self._single_chunk_summary(chunks[0], sources, role_name)

        return self._multi_chunk_summary(chunks, sources, role_name, query)

    def _extract_sources(self, chunks: List[Dict]) -> Dict[str, List[int]]:
        """提取来源信息：文件名 -> [页码列表]"""
        sources: Dict[str, List[int]] = {}
        for chunk in chunks:
            filename = chunk.get("source_file", chunk.get("file_path", "unknown"))
            page = chunk.get("source_page", 0)
            if filename not in sources:
                sources[filename] = []
            if page and page not in sources[filename]:
                sources[filename].append(page)
        return sources

    def _single_chunk_summary(self, chunk: Dict, sources: Dict, role_name: str) -> str:
        """单碎片摘要"""
        filename = next(iter(sources.keys()))
        pages = sources[filename]

        text = chunk.get("text", "")[:800]
        page_ref = f"第 {', '.join(map(str, sorted(pages)))} 页" if pages else ""

        prefix = self._get_role_prefix(role_name)

        if page_ref:
            return f"{prefix}根据《{filename}》{page_ref}所述：\n\n{text}\n\n---\n**参考来源**：{filename} {page_ref}"
        return f"{prefix}根据《{filename}》所述：\n\n{text}\n\n---\n**参考来源**：{filename}"

    def _multi_chunk_summary(self, chunks: List[Dict], sources: Dict, role_name: str, query: str) -> str:
        """多碎片摘要"""
        prefix = self._get_role_prefix(role_name)

        source_list = []
        for filename, pages in sorted(sources.items()):
            page_ref = f"第 {', '.join(map(str, sorted(pages)))} 页" if pages else ""
            source_list.append(f"- 《{filename}》{page_ref}".strip())

        key_points = self._extract_key_points(chunks, query)

        summary_parts = []
        summary_parts.append(f"{prefix}关于「{query}」，我在馆藏中找到了以下相关内容：")
        summary_parts.append("")

        if key_points:
            summary_parts.append("## 核心要点")
            for i, point in enumerate(key_points, 1):
                summary_parts.append(f"{i}. {point}")
            summary_parts.append("")

        summary_parts.append("## 参考来源")
        summary_parts.extend(source_list)

        return "\n".join(summary_parts)

    def _extract_key_points(self, chunks: List[Dict], query: str) -> List[str]:
        """从碎片中提取核心要点"""
        points = []
        seen = set()

        for chunk in chunks:
            text = chunk.get("text", "")
            lines = [l.strip() for l in text.split("\n") if l.strip()]

            for line in lines:
                if len(line) < 10 or len(line) > 100:
                    continue

                if line.lower() in seen:
                    continue
                seen.add(line.lower())

                if any(keyword in line for keyword in
                       ["重要", "注意", "关键", "核心", "必须", "建议", "需要"]):
                    points.append(line)

                if len(points) >= 5:
                    break

        return points[:5]

    def _get_role_prefix(self, role_name: str) -> str:
        """根据角色名称生成开场白前缀"""
        prefixes = {
            "知识馆长": "📚 【馆长摘要】",
            "技术导师": "🎓 【导师笔记】",
            "创意助手": "💡 【创意灵感】",
        }
        return prefixes.get(role_name, "📋 【摘要】")


inline_summarizer = InlineSummarizer()
