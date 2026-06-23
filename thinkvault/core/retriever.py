"""
检索引擎 — 向量检索 + BM25 混合检索 + Cross-encoder 重排序
+ 元数据过滤 + 分层检索 + BM25 索引持久化
"""

import json
import os
from pathlib import Path
from typing import Optional

from thinkvault.core import doc_summary_store
from thinkvault.core.container import container
from thinkvault.utils.logger import logger

# 意图判断阈值（可通过环境变量调整灵敏度）
_INTENT_SIMILARITY_THRESHOLD = float(
    os.environ.get("THINKVAULT_INTENT_THRESHOLD", "0.3")
)

# 检索结果最低相关性阈值（距离越近越好，超过此距离的视为不相关）
_MIN_RELEVANCE_DISTANCE = float(
    os.environ.get("THINKVAULT_MIN_RELEVANCE_DISTANCE", "1.5")
)

# 内置默认意图关键词列表（配置文件加载失败时的 fallback）
_DEFAULT_INTENT_KEYWORDS = [
    "文档", "文件", "资料", "数据", "知识库", "内容",
    "搜索", "查找", "帮我找", "在哪", "有没有", "写了什么",
    "根据", "按照", "基于", "参考", "提及", "提到", "说过",
    "上面", "前面", "以上", "之前", "刚才", "这段", "这个文件",
    "pdf", "docx", "txt", "xlsx", "pptx", "合同", "报告", "论文", "笔记",
    "总结", "概括", "归纳", "提取", "列出", "找出", "介绍",
    "什么是", "如何", "怎么", "为什么", "什么时候", "哪里",
    "哪位", "哪个", "哪些", "谁", "什么", "怎样",
    "说明", "描述", "解释", "定义", "含义", "意思",
    "讲一讲", "说一说", "聊一聊", "谈谈",
    "帮我", "可否", "能否", "可以", "能否帮忙",
    "关于", "有关", "相关", "涉及到",
    "what is", "how to", "explain", "describe", "summarize",
    "find", "search", "look up", "based on", "according",
]

# ── 性能优化配置（环境变量控制）───────────────────────────────────

# 是否跳过 Cross-encoder 重排序（0.5B~3B 小模型场景推荐开启，节省 200-500ms）
_SKIP_RERANK = os.environ.get("THINKVAULT_SKIP_RERANK", "").lower() in ("1", "true")

# Cross-encoder 重排序的候选数阈值（候选数低于此值时跳过重排序，收益不大）
_RERANK_MIN_CANDIDATES = int(os.environ.get("THINKVAULT_RERANK_MIN_CANDIDATES", "3"))

# 大规模知识库自动切换分层检索的 chunk 数阈值（0 表示禁用自动切换）
_HIERARCHICAL_THRESHOLD = int(
    os.environ.get("THINKVAULT_HIERARCHICAL_THRESHOLD", "5000")
)

# 默认检索 top_k（可通过环境变量调整，小模型建议 3）
_DEFAULT_TOP_K = int(os.environ.get("THINKVAULT_TOP_K", "5"))

# 是否启用 BM25 索引持久化（冷启动加速，20 万文件场景推荐开启）
_BM25_PERSIST = os.environ.get("THINKVAULT_BM25_PERSIST", "1").lower() in ("1", "true")


class _BM25Mixin:
    """BM25 索引管理：构建、持久化、检索"""

    def _init_bm25_state(self):
        self._bm25_cache: dict = {}
        self._bm25_chunk_counts: dict = {}

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """中英混合分词：优先 jieba 中文分词，fallback 逐字分词"""
        try:
            import jieba
            tokens: list[str] = []
            for word in jieba.cut(text):
                word = word.strip().lower()
                if word and not word.isspace():
                    tokens.append(word)
            return tokens
        except ImportError:
            # fallback: 中文逐字 + 英文按空格分词
            tokens_fb: list[str] = []
            buf = ""
            for ch in text:
                if ch.isascii() and ch.isalnum():
                    buf += ch.lower()
                else:
                    if buf:
                        tokens_fb.append(buf)
                        buf = ""
                    if ch.strip() and not ch.isspace():
                        tokens_fb.append(ch)
            if buf:
                tokens_fb.append(buf)
            return tokens_fb

    def invalidate_cache(self, knowledge_base: str):
        """清除指定知识库的 BM25 缓存"""
        self._bm25_cache.pop(knowledge_base, None)
        self._bm25_chunk_counts.pop(knowledge_base, None)

        # 同步清理磁盘持久化索引
        if _BM25_PERSIST:
            try:
                from thinkvault.core import bm25_index_store
                bm25_index_store.delete_index(knowledge_base)
            except Exception as e:
                logger.debug(f"清理 BM25 磁盘缓存失败（不影响运行）: {e}")

    def _get_bm25(self, knowledge_base: str):
        """获取或构建 BM25 索引（带增量更新和磁盘缓存）"""
        chunk_count = container.vector_store.get_chunk_count(knowledge_base)
        cached_count = self._bm25_chunk_counts.get(knowledge_base)

        if knowledge_base in self._bm25_cache and cached_count == chunk_count:
            return self._bm25_cache[knowledge_base]

        # 尝试从磁盘加载
        if _BM25_PERSIST and cached_count is None:
            result = self._load_bm25_from_disk(knowledge_base)
            if result is not None:
                self._bm25_cache[knowledge_base] = result
                self._bm25_chunk_counts[knowledge_base] = chunk_count
                return result

        # 从 ChromaDB 构建
        result = self._build_bm25_from_chroma(knowledge_base)
        if result is not None:
            self._bm25_cache[knowledge_base] = result
            self._bm25_chunk_counts[knowledge_base] = chunk_count
            if _BM25_PERSIST:
                self._save_bm25_to_disk(knowledge_base, result)
            return result

        return None

    def _build_bm25_from_chroma(self, knowledge_base: str):
        """从 ChromaDB 构建 BM25 索引（自动选择 bm25s / rank_bm25）"""
        try:
            collection = container.vector_store.get_or_create_collection(knowledge_base)
        except Exception:
            return None

        all_data = collection.get(include=["documents", "metadatas"])
        doc_ids = all_data.get("ids", [])
        doc_texts = all_data.get("documents", [])
        doc_metadatas = all_data.get("metadatas", [{}] * len(doc_ids))

        if not doc_ids:
            self._bm25_cache[knowledge_base] = None
            return None

        tokenized = [self._tokenize(t) for t in doc_texts]

        # 尝试使用 bm25s（高性能实现）
        try:
            import bm25s

            bm25 = bm25s.BM25(k1=1.5, b=0.75)
            bm25.index(tokenized)
            result = (bm25, doc_texts, doc_ids, doc_metadatas, "bm25s")
            logger.info(f"BM25 索引构建完成 (bm25s): 知识库 [{knowledge_base}], {len(doc_ids)} chunks")
        except ImportError:
            # 回退到 rank_bm25
            try:
                from rank_bm25 import BM25Okapi
                bm25 = BM25Okapi(tokenized)
                result = (bm25, doc_texts, doc_ids, doc_metadatas, "rank_bm25")
                logger.info(f"BM25 索引构建完成 (rank_bm25): 知识库 [{knowledge_base}], {len(doc_ids)} chunks")
            except ImportError:
                logger.warning("BM25 库未安装，BM25 检索不可用")
                self._bm25_cache[knowledge_base] = None
                return None
        except Exception as e:
            logger.warning(f"bm25s 构建失败，回退到 rank_bm25: {e}")
            try:
                from rank_bm25 import BM25Okapi
                bm25 = BM25Okapi(tokenized)
                result = (bm25, doc_texts, doc_ids, doc_metadatas, "rank_bm25")
                logger.info(f"BM25 索引构建完成 (rank_bm25 fallback): 知识库 [{knowledge_base}], {len(doc_ids)} chunks")
            except ImportError:
                self._bm25_cache[knowledge_base] = None
                return None

        return result

    def _load_bm25_from_disk(self, knowledge_base: str):
        """从磁盘加载 BM25 索引缓存"""
        try:
            from thinkvault.core import bm25_index_store
        except ImportError:
            return None

        chunk_count = container.vector_store.get_chunk_count(knowledge_base)
        index_data = bm25_index_store.load_index(knowledge_base, expected_chunk_count=chunk_count)
        if index_data is None:
            return None

        try:
            from rank_bm25 import BM25Okapi

            doc_ids = index_data["doc_ids"]
            doc_texts = index_data["doc_texts"]
            doc_metadatas = index_data["doc_metadatas"]
            bm25_corpus = index_data["bm25_corpus"]
            bm25_params = index_data.get("bm25_params", {})

            bm25 = self._reconstruct_bm25(bm25_corpus, bm25_params)

            logger.info(
                f"BM25 索引从磁盘加载成功: 知识库 [{knowledge_base}], "
                f"{len(doc_ids)} chunks"
            )
            return (bm25, doc_texts, doc_ids, doc_metadatas, "rank_bm25")

        except Exception as e:
            logger.warning(f"BM25 磁盘索引反序列化失败 [{knowledge_base}]: {e}")
            return None

    @staticmethod
    def _reconstruct_bm25(corpus: list[list[str]], params: dict):
        """从持久化数据重建 BM25Okapi 对象"""
        from rank_bm25 import BM25Okapi
        bm25 = BM25Okapi(corpus)
        if "doc_len" in params:
            bm25.doc_len = params["doc_len"]
        if "avgdl" in params:
            bm25.avgdl = params["avgdl"]
        if "doc_freqs" in params:
            bm25.doc_freqs = params["doc_freqs"]
        if "idf" in params:
            bm25.idf = params["idf"]
        if "k1" in params:
            bm25.k1 = params["k1"]
        if "b" in params:
            bm25.b = params["b"]
        if "epsilon" in params:
            bm25.epsilon = params["epsilon"]
        return bm25

    def _save_bm25_to_disk(
        self,
        knowledge_base: str,
        bm25_tuple: tuple,
    ):
        """将 BM25 索引持久化到磁盘（同步写入，gzip 压缩）"""
        try:
            from thinkvault.core import bm25_index_store
        except ImportError:
            return

        bm25, doc_texts, doc_ids, doc_metadatas, engine = bm25_tuple

        # 提取 BM25 参数
        bm25_params = {}
        bm25_corpus = []

        if engine == "bm25s":
            # bm25s: 从内部状态提取
            try:
                bm25_corpus = doc_texts  # 使用原始文本
                bm25_params = {"engine": "bm25s"}
            except Exception:
                pass
        else:
            # rank_bm25: 提取内部状态
            try:
                bm25_corpus = bm25.corpus
                bm25_params = {
                    "doc_len": bm25.doc_len,
                    "avgdl": bm25.avgdl,
                    "doc_freqs": bm25.doc_freqs,
                    "idf": bm25.idf,
                    "k1": bm25.k1,
                    "b": bm25.b,
                    "epsilon": bm25.epsilon,
                }
            except Exception as e:
                logger.debug(f"提取 BM25 参数失败: {e}")

        bm25_index_store.save_index(
            knowledge_base=knowledge_base,
            doc_ids=doc_ids,
            doc_texts=doc_texts,
            doc_metadatas=doc_metadatas,
            bm25_corpus=bm25_corpus,
            bm25_params=bm25_params,
        )

    def _bm25_search(
        self, query: str, knowledge_base: str, top_k: int
    ) -> list[dict]:
        """BM25 关键词检索"""
        bm25_data = self._get_bm25(knowledge_base)
        if bm25_data is None:
            return []

        # 解包 5-tuple: (bm25_engine, doc_texts, doc_ids, doc_metadatas, engine_name)
        bm25, doc_texts, doc_ids, doc_metadatas, engine = bm25_data

        tokenized_query = self._tokenize(query)

        if engine == "bm25s":
            return self._bm25s_search(bm25, tokenized_query, doc_ids, doc_texts, doc_metadatas, top_k)
        else:
            return self._rank_bm25_search(bm25, tokenized_query, doc_ids, doc_texts, doc_metadatas, top_k)

    @staticmethod
    def _bm25s_search(bm25, tokenized_query, doc_ids, doc_texts, doc_metadatas, top_k):
        """使用 bm25s 进行高性能 BM25 检索"""
        try:
            results_obj = bm25.retrieve(tokenized_query, k=top_k)

            doc_indices = results_obj.documents
            scores = results_obj.scores

            results: list[dict] = []
            for row_idx in range(len(doc_indices)):
                for col_idx in range(len(doc_indices[row_idx])):
                    idx = int(doc_indices[row_idx][col_idx])
                    score = float(scores[row_idx][col_idx])
                    if score > 0 and 0 <= idx < len(doc_ids):
                        results.append({
                            "id": doc_ids[idx],
                            "text": doc_texts[idx],
                            "metadata": doc_metadatas[idx] if idx < len(doc_metadatas) else {},
                            "score": score,
                            "source": "bm25",
                        })
                    if len(results) >= top_k:
                        break
                if len(results) >= top_k:
                    break
            return results
        except Exception as e:
            logger.debug(f"bm25s 检索失败: {e}")
            return []

    @staticmethod
    def _rank_bm25_search(bm25, tokenized_query, doc_ids, doc_texts, doc_metadatas, top_k):
        """使用 rank_bm25 进行 BM25 检索"""
        try:
            scores = bm25.get_scores(tokenized_query)
            scored = list(enumerate(scores))
            scored.sort(key=lambda x: x[1], reverse=True)

            results: list[dict] = []
            for idx, score in scored[:top_k]:
                if score > 0:
                    results.append({
                        "id": doc_ids[idx],
                        "text": doc_texts[idx],
                        "metadata": doc_metadatas[idx] if idx < len(doc_metadatas) else {},
                        "score": float(score),
                        "source": "bm25",
                    })
            return results
        except Exception as e:
            logger.warning(f"rank_bm25 检索失败: {e}")
            return []


class _IntentMixin:
    """意图分类：判断用户查询是否需要检索知识库"""

    def _init_intent_state(self):
        self._intent_keywords = self._load_intent_keywords()
        self._anchor_embeddings = None

    @staticmethod
    def _load_intent_keywords() -> list[str]:
        """从配置文件加载意图关键词列表"""
        env_path = os.environ.get("THINKVAULT_INTENT_KEYWORDS")
        if env_path:
            config_path = Path(env_path)
        else:
            config_path = Path(__file__).parent.parent / "data" / "intent_keywords.json"

        try:
            if config_path.is_file():
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                keywords = data.get("keywords", [])
                if keywords:
                    logger.info(f"已从配置文件加载 {len(keywords)} 个意图关键词: {config_path}")
                    return keywords
                logger.warning(f"配置文件中关键词列表为空，使用内置默认列表: {config_path}")
        except Exception as e:
            logger.warning(f"加载意图关键词配置文件失败 ({config_path}): {e}，使用内置默认列表")

        return list(_DEFAULT_INTENT_KEYWORDS)

    def _compute_anchor_embeddings(self):
        """计算意图判断锚点嵌入"""
        anchor_texts = [
            "请根据文档内容回答问题",
            "查找相关资料",
            "搜索知识库中的信息",
            "帮我找到相关文件",
            "文档里写了什么",
        ]
        try:
            embeddings = container.embedder.embed(anchor_texts)
            return embeddings
        except Exception:
            return None


class _ContextMixin:
    """上下文格式化：将检索结果拼接为 LLM 上下文"""

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


class Retriever(_BM25Mixin, _IntentMixin, _ContextMixin):
    """文档检索器，支持向量检索 + BM25 + Cross-encoder 混合检索"""

    def __init__(self):
        self._init_bm25_state()
        self._init_intent_state()
        self._cross_encoder = None   # CrossEncoder 实例，False 表示加载失败
        # Embedding 查询缓存：query -> (embedding, timestamp)
        self._embed_cache: dict = {}
        self._embed_cache_max = int(os.environ.get("THINKVAULT_EMBED_CACHE_SIZE", "128"))
        self._embed_cache_ttl = int(os.environ.get("THINKVAULT_EMBED_CACHE_TTL", "300"))  # 秒，默认5分钟
        # 持久化线程池，避免每次搜索重建
        from concurrent.futures import ThreadPoolExecutor
        self._search_pool = ThreadPoolExecutor(max_workers=1)

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

    # ── 向量检索 ──────────────────────────────────────────────────

    def _get_query_embedding(self, query: str):
        """获取查询嵌入（带 LRU 缓存 + TTL 过期）

        缓存策略：
        - LRU 淘汰：容量超限时删除最早插入的 key
        - TTL 过期：缓存条目超过 _embed_cache_ttl 秒后自动失效
        """
        import time as _time

        if query in self._embed_cache:
            embedding, ts = self._embed_cache[query]
            # TTL 检查
            if _time.monotonic() - ts < self._embed_cache_ttl:
                return embedding
            # 过期，移除
            del self._embed_cache[query]

        embedding = container.embedder.embed_single(query)

        if embedding is not None:
            # LRU 淘汰
            if len(self._embed_cache) >= self._embed_cache_max:
                oldest = next(iter(self._embed_cache))
                del self._embed_cache[oldest]
            self._embed_cache[query] = (embedding, _time.monotonic())

        return embedding

    def _vector_search(
        self, query: str, knowledge_base: str, top_k: int
    ) -> list[dict]:
        """向量语义检索（使用 Embedding 缓存）"""
        query_embedding = self._get_query_embedding(query)
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
        return self._classify_intent(message, knowledge_base)["should_retrieve"]

    def _classify_intent(self, message: str, knowledge_base: str) -> dict:
        """意图分类：判断用户查询的意图类型。

        返回：
            {
                "intent_type": "precise" | "exploratory" | "ambiguous",
                "should_retrieve": bool,
                "confidence": float,
                "reason": str
            }

        意图类型：
        - precise（精确）：问题明确指向特定信息，如"文档中提到的 API 是什么？"
        - exploratory（探索）：用户在探索主题，如"关于 Python 有哪些内容？"
        - ambiguous（模糊）：意图不明确，需要澄清，如"这个东西怎么用？"
        """
        if container.vector_store.get_chunk_count(knowledge_base) == 0:
            return {
                "intent_type": "ambiguous",
                "should_retrieve": False,
                "confidence": 0.0,
                "reason": "知识库为空",
            }

        msg_lower = message.lower()
        result = {
            "intent_type": "ambiguous",
            "should_retrieve": False,
            "confidence": 0.0,
            "reason": "",
        }

        precise_keywords = [
            "第", "页", "行", "段", "章节", "标题", "部分",
            "具体", "详细", "哪个", "哪些", "是谁", "什么是",
            "定义", "解释", "说明", "含义", "意思",
            "提到", "提及", "写了", "说了", "包含",
        ]

        exploratory_keywords = [
            "相关", "关于", "涉及", "有哪些", "有什么",
            "介绍", "概述", "总结", "概括", "归纳",
            "搜索", "查找", "帮我找", "探索", "了解",
            "学习", "研究", "分析", "对比", "比较",
        ]

        ambiguous_keywords = [
            "怎么", "如何", "能不能", "可以吗",
            "这个", "那个", "它", "这", "那",
            "用", "使用", "操作", "配置", "设置",
        ]

        precise_score = sum(1 for kw in precise_keywords if kw in msg_lower)
        exploratory_score = sum(1 for kw in exploratory_keywords if kw in msg_lower)
        ambiguous_score = sum(1 for kw in ambiguous_keywords if kw in msg_lower)

        total_score = precise_score + exploratory_score + ambiguous_score

        if total_score > 0:
            max_score = max(precise_score, exploratory_score, ambiguous_score)
            confidence = max_score / total_score

            if precise_score == max_score:
                result["intent_type"] = "precise"
                result["should_retrieve"] = True
                result["confidence"] = confidence
                result["reason"] = "精确意图：包含精确关键词"
            elif exploratory_score == max_score:
                result["intent_type"] = "exploratory"
                result["should_retrieve"] = True
                result["confidence"] = confidence
                result["reason"] = "探索意图：包含探索关键词"
            else:
                result["intent_type"] = "ambiguous"
                result["should_retrieve"] = False
                result["confidence"] = confidence
                result["reason"] = "模糊意图：包含模糊关键词"
        else:
            if any(kw in msg_lower for kw in self._intent_keywords):
                result["intent_type"] = "exploratory"
                result["should_retrieve"] = True
                result["confidence"] = 0.7
                result["reason"] = "通用检索关键词匹配"
            else:
                try:
                    if not container.embedder.is_loaded:
                        if not container.embedder.load():
                            return result

                    if self._anchor_embeddings is None:
                        anchors = [
                            "请帮我查找文档中的相关内容",
                            "根据已有资料回答这个问题",
                            "在知识库中搜索相关信息",
                        ]
                        self._anchor_embeddings = container.embedder.embed(anchors)
                        if self._anchor_embeddings is None:
                            return result

                    msg_emb = container.embedder.embed_single(message)
                    if msg_emb is None:
                        return result

                    anchor_embs = self._anchor_embeddings

                    import numpy as np

                    msg_arr = np.array(msg_emb)
                    max_sim = 0.0
                    for a in anchor_embs:
                        a_arr = np.array(a)
                        sim = np.dot(msg_arr, a_arr) / (
                            np.linalg.norm(msg_arr) * np.linalg.norm(a_arr) + 1e-9
                        )
                        max_sim = max(max_sim, sim)

                    if max_sim >= _INTENT_SIMILARITY_THRESHOLD:
                        result["intent_type"] = "exploratory"
                        result["should_retrieve"] = True
                        result["confidence"] = max_sim
                        result["reason"] = f"语义相似度匹配: {max_sim:.2f}"
                    else:
                        result["intent_type"] = "ambiguous"
                        result["should_retrieve"] = False
                        result["confidence"] = max_sim
                        result["reason"] = f"语义相似度不足: {max_sim:.2f}"

                except Exception:
                    pass

        return result

    # ── RRF 分数融合 ───────────────────────────────────────────────

    @staticmethod
    def _rrf_merge(
        vector_hits: list[dict],
        bm25_hits: list[dict],
        top_k: int,
        k: int = 60,
    ) -> list[dict]:
        """Reciprocal Rank Fusion: score = Σ 1/(k + rank_i)

        将向量检索和 BM25 检索的结果按排名倒数融合，
        替代简单去重，充分利用双路分数信息。
        """
        scores: dict[str, float] = {}
        all_hits: dict[str, dict] = {}

        for rank, h in enumerate(vector_hits):
            hid = h.get("id", "")
            if hid:
                scores[hid] = scores.get(hid, 0) + 1.0 / (k + rank + 1)
                all_hits[hid] = h

        for rank, h in enumerate(bm25_hits):
            hid = h.get("id", "")
            if hid:
                scores[hid] = scores.get(hid, 0) + 1.0 / (k + rank + 1)
                if hid not in all_hits:
                    all_hits[hid] = h

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        result = []
        for hid, rrf_score in ranked[:top_k]:
            hit = dict(all_hits[hid])
            hit["rrf_score"] = rrf_score
            result.append(hit)
        return result

    # ── 主检索入口 ────────────────────────────────────────────────

    def retrieve(
        self, query: str, knowledge_base: str = "default", top_k: int = 0
    ) -> list[dict]:
        """混合检索流程（向量 + BM25 并行执行）：
        1. 并行执行向量检索和 BM25 检索（各 top_k×2 候选）
        2. RRF 分数融合
        3. Cross-encoder 重排序（可通过 THINKVAULT_SKIP_RERANK=1 跳过）
        4. 取 top_k

        Args:
            top_k: 返回结果数量，0 表示使用环境变量 THINKVAULT_TOP_K 的值（默认 5）

        Returns:
            list[dict]: 检索结果列表。
            空列表表示"已检索但未找到相关结果"。
            调用方应通过 should_retrieve() 区分"不需要检索"和"检索了但没找到"。
        """
        if top_k <= 0:
            top_k = _DEFAULT_TOP_K
        candidate_k = top_k * 2

        # 并行执行向量检索和 BM25 检索
        vector_hits, bm25_hits = self._parallel_search(query, knowledge_base, candidate_k)

        # RRF 分数融合
        merged = self._rrf_merge(vector_hits, bm25_hits, top_k=candidate_k)

        if not merged:
            return []

        # Cross-encoder 重排序
        if not _SKIP_RERANK and len(merged) >= _RERANK_MIN_CANDIDATES:
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

    def _parallel_search(
        self, query: str, knowledge_base: str, candidate_k: int
    ) -> tuple[list[dict], list[dict]]:
        """并行执行向量检索和 BM25 检索

        使用持久化线程池将 BM25 检索移至后台线程，
        向量检索在主线程执行（ChromaDB 已有线程安全保护），
        两者并行运行，总耗时 = max(vector, bm25) 而非 vector + bm25。
        """
        # BM25 检索提交到线程池（BM25 是 CPU 密集型，适合后台线程）
        bm25_future = self._search_pool.submit(
            self._bm25_search, query, knowledge_base, candidate_k
        )
        # 向量检索在主线程执行
        vector_hits = self._vector_search(query, knowledge_base, candidate_k)
        # 等待 BM25 完成
        bm25_hits = bm25_future.result()

        return vector_hits, bm25_hits

    # 兼容旧接口
    def retrieve_with_rerank(
        self,
        query: str,
        knowledge_base: str = "default",
        top_k: int = 5,
        candidate_k: int = 20,
    ) -> list[dict]:
        return self.retrieve(query, knowledge_base, top_k)

    # ── 元数据过滤检索 ───────────────────────────────────────────

    def retrieve_with_filters(
        self,
        query: str,
        knowledge_base: str = "default",
        top_k: int = 5,
        file_types: list[str] | None = None,
        source_files: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> list[dict]:
        """带元数据过滤的检索

        实现方式：
        1. 获取 ChromaDB collection
        2. 构建 where 过滤条件（ChromaDB 原生支持 metadata filtering）
        3. 调用 collection.query() 进行向量检索
        4. 仍然叠加 BM25 检索（BM25 不支持过滤，需要后置过滤）
        5. 合并去重 + Cross-encoder 重排序
        """
        candidate_k = top_k * 2
        where_clause = self._build_where_clause(file_types, source_files, tags)

        # 向量检索（支持 ChromaDB where 过滤）
        vector_hits = self._vector_search_with_where(
            query, knowledge_base, candidate_k, where_clause
        )

        # BM25 检索（不支持原生过滤，需要后置过滤）
        bm25_hits = self._bm25_search(query, knowledge_base, candidate_k)
        if file_types or source_files:
            bm25_hits = self._post_filter_bm25(bm25_hits, file_types, source_files)

        # RRF 分数融合
        merged = self._rrf_merge(vector_hits, bm25_hits, top_k=candidate_k)

        if not merged:
            return []

        # Cross-encoder 重排序（可通过 THINKVAULT_SKIP_RERANK=1 跳过，节省 200-500ms）
        # 候选数低于阈值时跳过重排序（收益不大）
        if not _SKIP_RERANK and len(merged) >= _RERANK_MIN_CANDIDATES:
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

    @staticmethod
    def _build_where_clause(
        file_types: list[str] | None,
        source_files: list[str] | None,
        tags: list[str] | None,
    ) -> dict | None:
        """构建 ChromaDB where 过滤条件，条件为空时返回 None"""
        conditions: list[dict] = []

        if file_types:
            conditions.append({"file_type": {"$in": file_types}})
        if source_files:
            conditions.append({"source_file": {"$in": source_files}})
        if tags:
            conditions.append({"tags": {"$in": tags}})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    def _vector_search_with_where(
        self,
        query: str,
        knowledge_base: str,
        top_k: int,
        where: dict | None,
    ) -> list[dict]:
        """带 where 条件的向量检索"""
        query_embedding = container.embedder.embed_single(query)
        if query_embedding is None:
            return []

        try:
            collection = container.vector_store.get_or_create_collection(knowledge_base)
            query_kwargs = {
                "query_embeddings": [query_embedding],
                "n_results": top_k,
                "include": ["documents", "metadatas", "distances"],
            }
            if where:
                query_kwargs["where"] = where

            results = collection.query(**query_kwargs)

            hits = []
            if results["ids"] and results["ids"][0]:
                for i in range(len(results["ids"][0])):
                    hits.append({
                        "id": results["ids"][0][i],
                        "text": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                        "distance": results["distances"][0][i] if results["distances"] else 0,
                        "source": "vector",
                    })
            return hits
        except Exception as e:
            logger.warning(f"带过滤的向量检索失败，回退无过滤检索: {e}")
            return self._vector_search(query, knowledge_base, top_k)

    @staticmethod
    def _post_filter_bm25(
        hits: list[dict],
        file_types: list[str] | None,
        source_files: list[str] | None,
    ) -> list[dict]:
        """对 BM25 结果进行后置元数据过滤"""
        filtered = hits
        if file_types:
            file_types_set = set(file_types)
            filtered = [
                h for h in filtered
                if h.get("metadata", {}).get("file_type", "") in file_types_set
            ]
        if source_files:
            source_files_set = set(source_files)
            filtered = [
                h for h in filtered
                if h.get("metadata", {}).get("source_file", "") in source_files_set
            ]
        return filtered

    # ── 分层检索 ─────────────────────────────────────────────────

    def retrieve_hierarchical(
        self,
        query: str,
        knowledge_base: str = "default",
        top_k: int = 0,
        max_doc_count: int = 3,
    ) -> list[dict]:
        """分层检索：先摘要层筛选文档，再 chunk 层深入

        流程：
        1. 获取知识库中所有已生成摘要的文档（doc_summary_store）
        2. 用预计算摘要嵌入与 query 嵌入做余弦相似度匹配（无嵌入则实时计算）
        3. 选出最相关的 max_doc_count 个文档
        4. 在这些文档的 chunks 中进行精确检索（retrieve_with_filters 限定 source_files）
        5. 返回 chunk 级检索结果

        降级策略：
        - 如果没有摘要数据，直接调用 retrieve()
        - 如果摘要匹配失败，降级到 retrieve()

        性能说明：
        - 预计算嵌入模式下，摘要匹配 ~0.1s（numpy 余弦相似度）
        - 无预计算嵌入时，实时计算 20 万摘要嵌入需 60-120s，会自动降级
        """
        if top_k <= 0:
            top_k = _DEFAULT_TOP_K

        # 尝试使用预计算嵌入
        summaries_with_emb = doc_summary_store.get_embeddings_by_kb(
            knowledge_base, status="generated"
        )

        if not summaries_with_emb:
            # 没有摘要数据，降级为普通检索
            logger.info(f"知识库 [{knowledge_base}] 无摘要数据，降级为普通检索")
            return self.retrieve(query, knowledge_base, top_k)

        try:
            query_embedding = container.embedder.embed_single(query)
            if query_embedding is None:
                logger.warning("查询嵌入失败，降级为普通检索")
                return self.retrieve(query, knowledge_base, top_k)

            import numpy as np

            q_arr = np.array(query_embedding)
            q_norm = np.linalg.norm(q_arr) + 1e-9

            # 分离有预计算嵌入和无预计算嵌入的摘要
            precomputed = [s for s in summaries_with_emb if s.get("summary_embedding")]
            needs_compute = [s for s in summaries_with_emb if not s.get("summary_embedding")]

            scored_docs: list[tuple[float, str]] = []

            # 优先使用预计算嵌入（O(1) 查询开销）
            if precomputed:
                emb_matrix = np.array([s["summary_embedding"] for s in precomputed])
                # 批量余弦相似度计算
                norms = np.linalg.norm(emb_matrix, axis=1) + 1e-9
                sims = emb_matrix @ q_arr / (norms * q_norm)
                for i, sim in enumerate(sims):
                    scored_docs.append((float(sim), precomputed[i]["doc_id"]))

            # 对无预计算嵌入的摘要，实时计算（数量少时可接受）
            if needs_compute:
                texts = [s["summary"] for s in needs_compute]
                embeddings = container.embedder.embed(texts)
                if embeddings is not None:
                    for i, s_emb in enumerate(embeddings):
                        s_arr = np.array(s_emb)
                        sim = float(np.dot(q_arr, s_arr) / (np.linalg.norm(s_arr) * q_norm + 1e-9))
                        scored_docs.append((sim, needs_compute[i]["doc_id"]))

            if not scored_docs:
                logger.info("摘要匹配无结果，降级为普通检索")
                return self.retrieve(query, knowledge_base, top_k)

            # 按相似度排序，取 top max_doc_count
            scored_docs.sort(key=lambda x: x[0], reverse=True)
            top_docs = scored_docs[:max_doc_count]
            matched_source_files = [doc_id for _, doc_id in top_docs]

            logger.info(
                f"分层检索：摘要层匹配到 {len(matched_source_files)} 个文档，"
                f"进入 chunk 层精确检索"
            )

            # 在匹配文档的 chunks 中检索
            return self.retrieve_with_filters(
                query,
                knowledge_base=knowledge_base,
                top_k=top_k,
                source_files=matched_source_files,
            )

        except Exception as e:
            logger.warning(f"分层检索异常，降级为普通检索: {e}")
            return self.retrieve(query, knowledge_base, top_k)

    # ── 智能检索入口 ────────────────────────────────────────────────

    def retrieve_smart(
        self,
        query: str,
        knowledge_base: str = "default",
        top_k: int = 0,
        conversation_id: str | None = None,
        recent_count: int = 5,
    ) -> dict:
        """智能检索：根据知识库规模自动选择检索策略

        策略选择逻辑：
        - chunk 数 > _HIERARCHICAL_THRESHOLD 且有摘要数据 → 分层检索
        - 否则 → 普通混合检索（如有会话 ID 则带上下文）

        Returns:
            dict: {
                "results": [...],
                "conversation_context": "...",
                "strategy": "hierarchical" | "standard"
            }
        """
        if top_k <= 0:
            top_k = _DEFAULT_TOP_K

        chunk_count = container.vector_store.get_chunk_count(knowledge_base)

        # 大规模知识库 + 有摘要 → 分层检索
        if _HIERARCHICAL_THRESHOLD > 0 and chunk_count > _HIERARCHICAL_THRESHOLD:
            summaries = doc_summary_store.get_by_kb(knowledge_base, status="generated")
            if summaries:
                logger.info(
                    f"知识库 [{knowledge_base}] 共 {chunk_count} chunks "
                    f"(阈值 {_HIERARCHICAL_THRESHOLD})，启用分层检索"
                )
                results = self.retrieve_hierarchical(query, knowledge_base, top_k)
                return {
                    "results": results,
                    "conversation_context": "",
                    "strategy": "hierarchical",
                }

        # 普通检索（带/不带上下文）
        if conversation_id is not None:
            return {
                **self.retrieve_with_context(
                    query, knowledge_base, conversation_id, recent_count, top_k=top_k
                ),
                "strategy": "standard",
            }
        else:
            return {
                "results": self.retrieve(query, knowledge_base, top_k),
                "conversation_context": "",
                "strategy": "standard",
            }

    # ── 多轮对话上下文检索 ────────────────────────────────────────

    def retrieve_with_context(
        self,
        query: str,
        knowledge_base: str = "default",
        conversation_id: str | None = None,
        recent_count: int = 5,
        **kwargs,
    ) -> dict:
        """带历史对话上下文的检索

        当 conversation_id 不为 None 时，获取最近 N 条历史消息，
        将其拼接为上下文前缀来增强查询，提升多轮对话的检索效果。

        Args:
            query: 当前用户问题
            knowledge_base: 知识库名称
            conversation_id: 会话 ID，为 None 时退化为普通检索
            recent_count: 获取最近消息条数
            **kwargs: 传递给 retrieve() 的额外参数（如 top_k）

        Returns:
            dict: {
                "results": [...],           # 检索结果列表
                "conversation_context": "..." # 历史对话上下文字符串
            }
        """
        conversation_context = ""

        if conversation_id is not None:
            try:
                from thinkvault.core import conversation_store
                messages = conversation_store.get_recent_messages(
                    conversation_id, limit=recent_count
                )
                if messages:
                    context_lines = []
                    for msg in messages:
                        role = msg.get("role", "user")
                        content = msg.get("content", "")
                        context_lines.append(f"{role}: {content}")
                    conversation_context = "历史对话：\n" + "\n".join(context_lines)
            except Exception as e:
                logger.warning(f"获取对话历史失败: {e}")

        # 构建增强查询
        if conversation_context:
            enhanced_query = conversation_context + "\n当前问题：" + query
        else:
            enhanced_query = query

        # 执行检索
        results = self.retrieve(enhanced_query, knowledge_base, **kwargs)

        return {
            "results": results,
            "conversation_context": conversation_context,
        }

    # ── 缓存预热 ──────────────────────────────────────────────────

    def warmup(self, knowledge_base: str = "default"):
        """预热检索缓存：预构建 BM25 索引 + 预加载 Embedding 模型

        应在服务启动时调用，避免首次查询时的冷启动延迟。
        """
        import time as _time

        t0 = _time.perf_counter()

        # 预加载 Embedding 模型
        if not container.embedder.is_loaded:
            container.embedder.load()

        embed_time = _time.perf_counter() - t0

        # 预构建 BM25 索引
        t1 = _time.perf_counter()
        chunk_count = container.vector_store.get_chunk_count(knowledge_base)
        if chunk_count > 0:
            self._get_bm25(knowledge_base)
        bm25_time = _time.perf_counter() - t1

        # 预计算一个查询的 Embedding（触发 ONNX 编译优化）
        t2 = _time.perf_counter()
        if container.embedder.is_loaded:
            container.embedder.embed_single("预热查询")
        embed_warmup_time = _time.perf_counter() - t2

        logger.info(
            f"检索缓存预热完成: 知识库 [{knowledge_base}], "
            f"模型加载 {embed_time:.1f}s, BM25构建 {bm25_time:.1f}s, "
            f"Embedding预热 {embed_warmup_time:.2f}s"
        )


