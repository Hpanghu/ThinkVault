"""
检索引擎 — 向量检索 + BM25 混合检索 + Cross-encoder 重排序
"""

import os
from typing import Optional

from thinkvault.core.container import container
from thinkvault.utils.logger import logger

# 意图判断阈值（可通过环境变量调整灵敏度）
_INTENT_SIMILARITY_THRESHOLD = float(
    os.environ.get("THINKVAULT_INTENT_THRESHOLD", "0.3")
)


class Retriever:
    """文档检索器，支持向量检索 + BM25 + Cross-encoder 混合检索"""

    def __init__(self):
        self._bm25_cache: dict = {}  # knowledge_base -> (BM25 model, doc_texts, doc_ids)
        self._cross_encoder = None   # CrossEncoder 实例，False 表示加载失败

    # ── Cross-encoder ──────────────────────────────────────────────

    def _get_cross_encoder(self):
        """惰性加载 CrossEncoder 模型"""
        if self._cross_encoder is not None:
            return self._cross_encoder if self._cross_encoder is not False else None

        try:
            from sentence_transformers import CrossEncoder

            model_name = os.environ.get(
                "THINKVAULT_CROSS_ENCODER",
                "cross-encoder/ms-marco-MiniLM-L-6-v2",
            )
            self._cross_encoder = CrossEncoder(model_name)
            logger.info(f"Cross-encoder 加载成功: {model_name}")
            return self._cross_encoder
        except OSError as e:
            logger.warning(
                f"Cross-encoder 模型首次加载需要从 HuggingFace 下载 (~80MB)，"
                f"请确保网络畅通。若持续失败可设置环境变量 "
                f"THINKVAULT_CROSS_ENCODER 指向本地模型路径。"
                f"原始错误: {e}"
            )
            self._cross_encoder = False
            return None
        except Exception as e:
            logger.warning(f"Cross-encoder 加载失败，重排序将跳过: {e}")
            self._cross_encoder = False
            return None

    # ── 分词 ──────────────────────────────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """中英混合分词：中文逐字 + 英文按空格/标点分词"""
        tokens: list[str] = []
        buf = ""
        for ch in text:
            if ch.isascii() and ch.isalnum():
                buf += ch.lower()
            else:
                if buf:
                    tokens.append(buf)
                    buf = ""
                if ch.strip() and not ch.isspace():
                    tokens.append(ch)
        if buf:
            tokens.append(buf)
        return tokens

    # ── BM25 ───────────────────────────────────────────────────────

    def invalidate_cache(self, knowledge_base: str):
        """公开方法：删除指定知识库的 BM25/向量缓存

        当知识库被删除时应调用此方法，避免后续重建同名 KB 时使用过期缓存。
        """
        if knowledge_base in self._bm25_cache:
            del self._bm25_cache[knowledge_base]
            logger.info(f"已清理知识库 [{knowledge_base}] 的检索缓存")

    def _get_bm25(self, knowledge_base: str):
        """获取或构建 BM25 索引（缓存）"""
        if knowledge_base in self._bm25_cache:
            return self._bm25_cache[knowledge_base]

        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.warning("rank-bm25 未安装，BM25 检索不可用")
            self._bm25_cache[knowledge_base] = None
            return None

        collection = container.vector_store.get_or_create_collection(knowledge_base)
        all_data = collection.get(include=["documents"])

        if not all_data.get("ids"):
            self._bm25_cache[knowledge_base] = None
            return None

        doc_texts = all_data["documents"]
        doc_ids = all_data["ids"]
        tokenized = [self._tokenize(t) for t in doc_texts]

        bm25 = BM25Okapi(tokenized)
        self._bm25_cache[knowledge_base] = (bm25, doc_texts, doc_ids)
        return (bm25, doc_texts, doc_ids)

    def _bm25_search(
        self, query: str, knowledge_base: str, top_k: int
    ) -> list[dict]:
        """BM25 关键字检索"""
        cache = self._get_bm25(knowledge_base)
        if cache is None:
            return []

        bm25, doc_texts, doc_ids = cache
        tokenized_query = self._tokenize(query)
        scores = bm25.get_scores(tokenized_query)

        top_indices = sorted(
            range(len(scores)), key=lambda i: scores[i], reverse=True
        )[:top_k]

        results: list[dict] = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append({
                    "id": doc_ids[idx],
                    "text": doc_texts[idx],
                    "metadata": {},
                    "score": float(scores[idx]),
                    "source": "bm25",
                })
        return results

    # ── 向量检索 ──────────────────────────────────────────────────

    def _vector_search(
        self, query: str, knowledge_base: str, top_k: int
    ) -> list[dict]:
        """向量语义检索"""
        query_embedding = container.embedder.embed_single(query)
        if query_embedding is None:
            return []

        hits = container.vector_store.search(
            knowledge_base, query_embedding, top_k=top_k
        )
        for h in hits:
            h["source"] = "vector"
        return hits

    # ── 意图判断 ──────────────────────────────────────────────────

    def should_retrieve(self, message: str, knowledge_base: str) -> bool:
        """判断问题是否需要触发文档检索。

        两级判断：
        1. 快速关键词匹配（覆盖绝大部分场景）
        2. 语义兜底：用 embedder 计算用户消息与检索意图锚点的相似度
        """
        if container.vector_store.get_chunk_count(knowledge_base) == 0:
            return False

        msg_lower = message.lower()

        # ── 一级：扩展关键词词表 ──
        _keywords = [
            # 中文核心名词
            "文档", "文件", "资料", "数据", "知识库", "内容",
            # 搜索/查找动词
            "搜索", "查找", "帮我找", "在哪", "有没有", "写了什么",
            # 引用/依据
            "根据", "按照", "基于", "参考", "提及", "提到", "说过",
            # 上下文指代
            "上面", "前面", "以上", "之前", "刚才", "这段", "这个文件",
            # 文件格式
            "pdf", "docx", "txt", "xlsx", "pptx", "合同", "报告", "论文", "笔记",
            # 操作动词
            "总结", "概括", "归纳", "提取", "列出", "找出", "介绍",
            # 疑问词
            "什么是", "如何", "怎么", "为什么", "什么时候", "哪里",
            "哪位", "哪个", "哪些", "谁", "什么", "怎样",
            # 指令
            "说明", "描述", "解释", "定义", "含义", "意思",
            "讲一讲", "说一说", "聊一聊", "谈谈",
            "帮我", "可否", "能否", "可以", "能否帮忙",
            "关于", "有关", "相关", "涉及到",
            # 英文补充
            "what is", "how to", "explain", "describe", "summarize",
            "find", "search", "look up", "based on", "according",
        ]

        if any(kw in msg_lower for kw in _keywords):
            return True

        # ── 二级：语义相似度兜底 ──
        try:
            if not container.embedder.is_loaded:
                if not container.embedder.load():
                    return False

            anchors = [
                "请帮我查找文档中的相关内容",
                "根据已有资料回答这个问题",
                "在知识库中搜索相关信息",
            ]

            msg_emb = container.embedder.embed_single(message)
            if msg_emb is None:
                return False

            anchor_embs = container.embedder.embed(anchors)
            if anchor_embs is None:
                return False

            import numpy as np

            msg_arr = np.array(msg_emb)
            max_sim = 0.0
            for a in anchor_embs:
                a_arr = np.array(a)
                sim = np.dot(msg_arr, a_arr) / (
                    np.linalg.norm(msg_arr) * np.linalg.norm(a_arr) + 1e-9
                )
                max_sim = max(max_sim, sim)

            return max_sim >= _INTENT_SIMILARITY_THRESHOLD
        except Exception:
            return False

    # ── 主检索入口 ────────────────────────────────────────────────

    def retrieve(
        self, query: str, knowledge_base: str = "default", top_k: int = 5
    ) -> list[dict]:
        """混合检索流程：
        1. 向量检索 top_k×2 候选
        2. BM25 检索 top_k×2 候选
        3. 按 ID 合并去重
        4. Cross-encoder 重排序
        5. 取 top_k
        """
        candidate_k = top_k * 2

        vector_hits = self._vector_search(query, knowledge_base, candidate_k)
        bm25_hits = self._bm25_search(query, knowledge_base, candidate_k)

        # 合并去重（按 chunk ID）
        seen_ids: set = set()
        merged: list[dict] = []
        for h in vector_hits + bm25_hits:
            hid = h.get("id", "")
            if hid not in seen_ids:
                seen_ids.add(hid)
                merged.append(h)

        if not merged:
            return []

        # Cross-encoder 重排序
        cross_encoder = self._get_cross_encoder()
        if cross_encoder and len(merged) > 1:
            try:
                pairs = [(query, h["text"]) for h in merged]
                scores = cross_encoder.predict(pairs)
                for i, h in enumerate(merged):
                    h["rerank_score"] = float(scores[i])
                merged.sort(
                    key=lambda h: h.get("rerank_score", 0), reverse=True
                )
            except Exception as e:
                logger.warning(f"Cross-encoder 重排序失败: {e}")

        return merged[:top_k]

    # 兼容旧接口
    def retrieve_with_rerank(
        self,
        query: str,
        knowledge_base: str = "default",
        top_k: int = 5,
        candidate_k: int = 20,
    ) -> list[dict]:
        return self.retrieve(query, knowledge_base, top_k)

    # ── 上下文格式化 ──────────────────────────────────────────────

    def format_context(
        self, hits: list[dict], max_chars: int = 3000
    ) -> tuple[str, list[str]]:
        """将检索结果拼接为模型上下文，返回 (context_text, sources)。

        当单个片段超过 max_chars 时截断它而非跳过，保证至少有一个片段返回。
        """
        context_parts: list[str] = []
        sources: list[str] = []
        total_chars = 0

        for hit in hits:
            text = hit["text"]
            source_file = hit.get("metadata", {}).get("source_file", "未知")
            source_page = hit.get("metadata", {}).get("source_page", 0)
            source_str = (
                f"{source_file}" + (f" P{source_page}" if source_page else "")
            )

            segment = f"[来源: {source_str}]\n{text}"
            seg_len = len(segment)

            if total_chars + seg_len <= max_chars:
                sources.append(source_str)
                context_parts.append(segment)
                total_chars += seg_len
            elif total_chars == 0:
                truncated = segment[:max_chars] + "..."
                sources.append(source_str)
                context_parts.append(truncated)
                break
            elif total_chars < max_chars:
                remaining = max_chars - total_chars
                if remaining > 60:
                    truncated = segment[:remaining] + "..."
                    sources.append(source_str)
                    context_parts.append(truncated)
                break
            else:
                break

        return "\n\n---\n\n".join(context_parts), sources