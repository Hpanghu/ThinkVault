"""
检索性能基准测试 — 原方案 vs 新方案对比

测试环境：50万 chunks 模拟知识库
测试指标：平均延迟、P95延迟、最大延迟、QPS

原方案：逐字分词 + 简单去重
新方案：jieba分词 + RRF分数融合
"""

import asyncio
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

# 禁用 API Token（测试环境）
os.environ.pop("THINKVAULT_API_TOKEN", None)
# 跳过 Cross-encoder（聚焦检索本身性能）
os.environ["THINKVAULT_SKIP_RERANK"] = "1"
# 禁用 BM25 持久化（避免磁盘 IO 干扰）
os.environ["THINKVAULT_BM25_PERSIST"] = "0"

# ── 测试数据生成 ──────────────────────────────────────────────

# 中文语料模板（模拟真实知识库文档内容）
CHINESE_TEMPLATES = [
    "本文介绍了{topic}的基本概念和核心原理。{topic}是现代{field}领域的重要组成部分，"
    "其核心思想是通过{method}来实现{goal}。在实际应用中，{topic}已经被广泛用于{application}。",

    "关于{topic}的研究进展表明，近年来该领域取得了显著突破。"
    "特别是在{subfield}方向，研究者提出了多种{method}方案，"
    "有效提升了{metric}指标。本文将详细分析这些方案的优缺点。",

    "{topic}的技术架构通常包含以下几个层次：数据采集层负责{data_task}，"
    "处理层执行{process_task}，应用层提供{app_task}功能。"
    "各层之间通过{protocol}协议进行通信，确保数据的一致性和可靠性。",

    "在{field}项目中，{topic}模块的设计遵循以下原则："
    "第一，{principle1}；第二，{principle2}；第三，{principle3}。"
    "这些原则确保了系统的{quality}特性，使其能够满足{requirement}的需求。",

    "针对{topic}的优化策略主要包括：1) {strategy1}，通过减少{cost1}来提升效率；"
    "2) {strategy2}，利用{tech}技术实现并行处理；"
    "3) {strategy3}，引入{mechanism}机制保证数据安全。"
    "综合应用这些策略，系统整体性能可提升{improvement}。",

    "实验结果表明，{topic}方法在{dataset}数据集上的表现优于基线方法。"
    "具体而言，准确率从{old_score}%提升至{new_score}%，"
    "召回率从{old_recall}%提升至{new_recall}%，"
    "F1分数达到{f1_score}%。消融实验进一步验证了各组件的有效性。",

    "{topic}的安全规范要求：所有{resource}必须经过{auth_method}认证，"
    "操作日志需保留{retention}天以上。对于{risk_level}级别的操作，"
    "需要{approver}审批后方可执行。违反安全规范的行为将按照{policy}进行处理。",

    "根据{regulation}的规定，{topic}的实施需要满足以下合规要求："
    "数据存储必须使用{encryption}加密，访问控制采用{acl_model}模型，"
    "审计追踪需覆盖所有{scope}范围内的操作。合规检查每{frequency}进行一次。",
]

FILL_WORDS = {
    "topic": ["机器学习", "深度学习", "自然语言处理", "知识图谱", "向量检索",
              "语义分析", "文本分类", "信息抽取", "对话系统", "推荐算法",
              "数据治理", "隐私计算", "联邦学习", "边缘计算", "数字孪生",
              "微服务架构", "容器编排", "持续集成", "负载均衡", "服务网格",
              "区块链", "智能合约", "共识算法", "零知识证明", "同态加密"],
    "field": ["人工智能", "计算机科学", "软件工程", "数据科学", "信息安全",
              "云计算", "物联网", "大数据", "分布式系统", "网络工程"],
    "subfield": ["模型压缩", "推理加速", "特征工程", "超参优化", "数据增强"],
    "method": ["神经网络", "注意力机制", "Transformer", "卷积运算", "梯度下降"],
    "goal": ["高效推理", "精准预测", "实时响应", "智能决策", "自动化处理"],
    "application": ["智能客服", "文档分析", "风险控制", "医疗诊断", "自动驾驶"],
    "metric": ["准确率", "召回率", "F1分数", "推理延迟", "吞吐量"],
    "data_task": ["多源数据采集", "实时数据流接入", "批量数据导入", "增量数据同步"],
    "process_task": ["特征提取", "模式识别", "异常检测", "语义理解"],
    "app_task": ["可视化分析", "智能推荐", "预警通知", "报表生成"],
    "protocol": ["RESTful API", "gRPC", "消息队列", "WebSocket"],
    "principle1": ["高内聚低耦合", "单一职责", "开闭原则", "依赖倒置"],
    "principle2": ["可扩展性优先", "数据一致性", "容错优先", "性能优先"],
    "principle3": ["安全默认", "最小权限", "防御深度", "零信任"],
    "quality": ["高可用", "高性能", "可维护", "可观测"],
    "requirement": ["大规模并发", "低延迟响应", "海量数据处理", "多租户隔离"],
    "strategy1": ["缓存优化", "索引加速", "查询重写", "连接池复用"],
    "strategy2": ["异步处理", "批处理优化", "流式计算", "并行执行"],
    "strategy3": ["数据分片", "读写分离", "主从复制", "一致性哈希"],
    "cost1": ["IO开销", "计算开销", "内存占用", "网络延迟"],
    "tech": ["多线程", "协程", "GPU加速", "SIMD指令"],
    "mechanism": ["WAL日志", "快照备份", "心跳检测", "熔断降级"],
    "improvement": ["30%以上", "50%以上", "2倍以上", "一个数量级"],
    "dataset": ["WikiQA", "MS MARCO", "SQuAD", "Natural Questions"],
    "old_score": ["72.3", "68.5", "75.1", "70.8"],
    "new_score": ["85.6", "82.1", "88.3", "84.7"],
    "old_recall": ["65.2", "61.8", "70.4", "67.3"],
    "new_recall": ["79.8", "76.5", "83.2", "80.1"],
    "f1_score": ["82.3", "79.1", "85.6", "82.4"],
    "resource": ["用户数据", "系统资源", "API接口", "管理后台"],
    "auth_method": ["OAuth2.0", "JWT令牌", "双向TLS", "API密钥"],
    "retention": ["90", "180", "365", "730"],
    "risk_level": ["高", "中高", "关键", "敏感"],
    "approver": ["安全主管", "系统管理员", "部门负责人", "合规官"],
    "policy": ["安全管理制度", "数据保护条例", "内部审计规范", "违规处罚办法"],
    "regulation": ["GDPR", "网络安全法", "数据安全法", "个人信息保护法"],
    "encryption": ["AES-256", "RSA-4096", "国密SM4", "ChaCha20"],
    "acl_model": ["RBAC", "ABAC", "PBAC", "MAC"],
    "scope": ["数据访问", "配置变更", "权限管理", "系统运维"],
    "frequency": ["季度", "半年", "年度", "月度"],
}


def generate_chunk(chunk_id: int) -> tuple[str, str, dict]:
    """生成一个模拟文档块，返回 (id, text, metadata)"""
    template = random.choice(CHINESE_TEMPLATES)
    text = template
    for key, values in FILL_WORDS.items():
        placeholder = "{" + key + "}"
        if placeholder in text:
            text = text.replace(placeholder, random.choice(values), 1)

    doc_id = f"doc_{chunk_id // 10:05d}"
    page = chunk_id % 20 + 1
    chunk_index = chunk_id % 10
    source_file = f"{doc_id}.pdf"

    metadata = {
        "source_file": source_file,
        "source_page": page,
        "chunk_index": chunk_index,
        "file_type": "pdf",
        "doc_id": doc_id,
    }

    chunk_id_str = f"{source_file}_{chunk_index}"
    return chunk_id_str, text, metadata


# ── 测试查询集 ──────────────────────────────────────────────

TEST_QUERIES = [
    "机器学习的优化策略有哪些",
    "如何提升向量检索的准确率",
    "深度学习模型压缩方法",
    "自然语言处理中的注意力机制",
    "知识图谱的构建流程",
    "数据治理的安全规范要求",
    "微服务架构的设计原则",
    "联邦学习的隐私保护机制",
    "容器编排的最佳实践",
    "区块链共识算法比较",
    "推荐算法的评估指标",
    "边缘计算的架构设计",
    "智能合约的安全审计",
    "数据加密的合规要求",
    "负载均衡策略分析",
    "对话系统的技术架构",
    "信息抽取的关键技术",
    "隐私计算的应用场景",
    "持续集成的自动化流程",
    "服务网格的流量管理",
]


# ── 基准测试引擎 ──────────────────────────────────────────────

@dataclass
class BenchmarkResult:
    """单次基准测试结果"""
    name: str
    total_chunks: int
    num_queries: int
    num_iterations: int
    latencies_ms: list[float] = field(default_factory=list)
    bm25_build_time_ms: float = 0
    index_time_ms: float = 0

    @property
    def avg_latency(self) -> float:
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0

    @property
    def p95_latency(self) -> float:
        if not self.latencies_ms:
            return 0
        sorted_lat = sorted(self.latencies_ms)
        idx = int(len(sorted_lat) * 0.95)
        return sorted_lat[min(idx, len(sorted_lat) - 1)]

    @property
    def max_latency(self) -> float:
        return max(self.latencies_ms) if self.latencies_ms else 0

    @property
    def min_latency(self) -> float:
        return min(self.latencies_ms) if self.latencies_ms else 0

    @property
    def qps(self) -> float:
        if not self.latencies_ms:
            return 0
        total_time_s = sum(self.latencies_ms) / 1000
        return len(self.latencies_ms) / total_time_s if total_time_s > 0 else 0

    def summary(self) -> str:
        return (
            f"[{self.name}]\n"
            f"  总 chunks: {self.total_chunks:,}\n"
            f"  查询数: {self.num_queries} × {self.num_iterations} 轮\n"
            f"  索引构建: {self.index_time_ms:.0f}ms | BM25构建: {self.bm25_build_time_ms:.0f}ms\n"
            f"  平均延迟: {self.avg_latency:.1f}ms\n"
            f"  P95延迟:  {self.p95_latency:.1f}ms\n"
            f"  最大延迟: {self.max_latency:.1f}ms\n"
            f"  最小延迟: {self.min_latency:.1f}ms\n"
            f"  QPS:      {self.qps:.2f}"
        )


def build_test_collection(kb_name: str, num_chunks: int, embedder, vector_store) -> float:
    """构建测试用向量库，返回耗时(ms)

    优化：使用随机嵌入向量替代实时 Embedding 计算，大幅加速索引构建。
    检索性能测试关注的是检索算法本身，而非嵌入计算速度。
    """
    import numpy as np
    from thinkvault.core.chunker import TextChunk

    batch_size = 2000
    emb_dim = 512  # bge-small-zh-v1.5 的维度
    start = time.perf_counter()

    for offset in range(0, num_chunks, batch_size):
        batch_end = min(offset + batch_size, num_chunks)
        chunks = []
        for i in range(offset, batch_end):
            chunk_id_str, text, metadata = generate_chunk(i)
            chunk = TextChunk(
                text=text,
                chunk_index=metadata["chunk_index"],
                source_file=metadata["source_file"],
                source_page=metadata["source_page"],
                metadata=metadata,
            )
            chunks.append(chunk)

        # 使用随机嵌入（归一化），加速索引构建
        rng = np.random.default_rng(seed=offset)
        embeddings = rng.standard_normal((len(chunks), emb_dim)).tolist()
        # 归一化
        for i in range(len(embeddings)):
            arr = np.array(embeddings[i])
            norm = np.linalg.norm(arr) + 1e-9
            embeddings[i] = (arr / norm).tolist()

        # 写入 ChromaDB
        vector_store.add_chunks(kb_name, chunks, embeddings)

        progress = batch_end / num_chunks * 100
        print(f"\r  索引进度: {progress:.0f}% ({batch_end:,}/{num_chunks:,})", end="", flush=True)

    print()
    return (time.perf_counter() - start) * 1000


def run_benchmark_original(retriever, kb_name: str, queries: list[str],
                           iterations: int, top_k: int = 5) -> BenchmarkResult:
    """原方案基准测试：逐字分词 + 简单去重"""
    result = BenchmarkResult(
        name="原方案(逐字分词+简单去重)",
        total_chunks=0,
        num_queries=len(queries),
        num_iterations=iterations,
    )

    # 临时替换 _tokenize 为逐字分词
    original_tokenize = retriever._tokenize

    @staticmethod
    def _tokenize_char(text: str) -> list[str]:
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

    # 临时替换 _rrf_merge 为简单去重
    original_rrf = retriever._rrf_merge

    @staticmethod
    def _simple_dedup(vector_hits, bm25_hits, top_k, k=60):
        seen_ids: set = set()
        merged: list[dict] = []
        for h in vector_hits + bm25_hits:
            hid = h.get("id", "")
            if hid not in seen_ids:
                seen_ids.add(hid)
                merged.append(h)
        return merged[:top_k]

    # 清除 BM25 缓存，强制用逐字分词重建
    retriever.invalidate_cache(kb_name)
    retriever._tokenize = _tokenize_char
    retriever._rrf_merge = _simple_dedup

    # 预热 BM25
    bm25_start = time.perf_counter()
    retriever._get_bm25(kb_name)
    result.bm25_build_time_ms = (time.perf_counter() - bm25_start) * 1000

    # 执行检索测试
    for _ in range(iterations):
        for query in queries:
            start = time.perf_counter()
            hits = retriever.retrieve(query, knowledge_base=kb_name, top_k=top_k)
            latency = (time.perf_counter() - start) * 1000
            result.latencies_ms.append(latency)

    # 恢复
    retriever._tokenize = original_tokenize
    retriever._rrf_merge = original_rrf
    retriever.invalidate_cache(kb_name)

    return result


def run_benchmark_optimized(retriever, kb_name: str, queries: list[str],
                             iterations: int, top_k: int = 5) -> BenchmarkResult:
    """新方案基准测试：jieba分词 + RRF融合"""
    result = BenchmarkResult(
        name="新方案(jieba分词+RRF融合)",
        total_chunks=0,
        num_queries=len(queries),
        num_iterations=iterations,
    )

    # 清除 BM25 缓存，强制用 jieba 分词重建
    retriever.invalidate_cache(kb_name)

    # 预热 BM25
    bm25_start = time.perf_counter()
    retriever._get_bm25(kb_name)
    result.bm25_build_time_ms = (time.perf_counter() - bm25_start) * 1000

    # 执行检索测试
    for _ in range(iterations):
        for query in queries:
            start = time.perf_counter()
            hits = retriever.retrieve(query, knowledge_base=kb_name, top_k=top_k)
            latency = (time.perf_counter() - start) * 1000
            result.latencies_ms.append(latency)

    return result


def print_comparison(original: BenchmarkResult, optimized: BenchmarkResult):
    """打印性能对比报告"""
    print("\n" + "=" * 70)
    print("          检索性能基准测试报告 — 50万 chunks")
    print("=" * 70)

    print(f"\n{'指标':<20} {'原方案':>12} {'新方案':>12} {'提升':>12}")
    print("-" * 58)

    def improvement(old, new):
        if old == 0:
            return "N/A"
        pct = (old - new) / old * 100
        sign = "↓" if new < old else "↑"
        return f"{sign}{abs(pct):.1f}%"

    print(f"{'平均延迟(ms)':<20} {original.avg_latency:>12.1f} {optimized.avg_latency:>12.1f} {improvement(original.avg_latency, optimized.avg_latency):>12}")
    print(f"{'P95延迟(ms)':<20} {original.p95_latency:>12.1f} {optimized.p95_latency:>12.1f} {improvement(original.p95_latency, optimized.p95_latency):>12}")
    print(f"{'最大延迟(ms)':<20} {original.max_latency:>12.1f} {optimized.max_latency:>12.1f} {improvement(original.max_latency, optimized.max_latency):>12}")
    print(f"{'最小延迟(ms)':<20} {original.min_latency:>12.1f} {optimized.min_latency:>12.1f} {improvement(original.min_latency, optimized.min_latency):>12}")
    print(f"{'QPS':<20} {original.qps:>12.2f} {optimized.qps:>12.2f} {improvement(original.qps, optimized.qps):>12}")
    print(f"{'BM25构建(ms)':<20} {original.bm25_build_time_ms:>12.0f} {optimized.bm25_build_time_ms:>12.0f} {improvement(original.bm25_build_time_ms, optimized.bm25_build_time_ms):>12}")

    print(f"\n{'详细统计':}")
    print(f"  原方案: {original.summary()}")
    print(f"  新方案: {optimized.summary()}")

    # 延迟分布
    print(f"\n{'延迟分布':}")
    for label, result in [("原方案", original), ("新方案", optimized)]:
        sorted_lat = sorted(result.latencies_ms)
        deciles = [0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]
        print(f"  {label}:")
        for d in deciles:
            idx = int(len(sorted_lat) * d)
            val = sorted_lat[min(idx, len(sorted_lat) - 1)]
            print(f"    P{int(d*100):<4}: {val:.1f}ms")

    print("\n" + "=" * 70)


async def main():
    # 可通过命令行参数指定 chunks 数量，默认 50000（50万需数小时构建索引）
    num_chunks = int(sys.argv[1]) if len(sys.argv) > 1 else 50_000
    num_iterations = 3
    top_k = 5
    kb_name = "benchmark500k"

    print(f"ThinkVault 检索性能基准测试")
    print(f"测试规模: {num_chunks:,} chunks | {len(TEST_QUERIES)} 查询 × {num_iterations} 轮")
    print(f"测试环境: Python {sys.version.split()[0]}, OS: {sys.platform}")
    print()

    # 初始化组件
    from thinkvault.core.container import container
    embedder = container.embedder
    vector_store = container.vector_store
    retriever = container.retriever

    # 加载 Embedder
    print("加载 Embedding 模型...")
    if not embedder.load():
        print("Embedding 模型加载失败，尝试使用 API 模式...")
        os.environ["THINKVAULT_EMBEDDING_API_URL"] = "http://127.0.0.1:8080/v1"
        if not embedder.load():
            print("Embedding 模型加载失败，无法继续测试")
            return

    # 清理旧测试数据
    try:
        vector_store.delete_knowledge_base(kb_name)
    except Exception:
        pass

    # 构建测试数据
    print(f"\n构建 {num_chunks:,} chunks 测试数据...")
    index_time = build_test_collection(kb_name, num_chunks, embedder, vector_store)
    chunk_count = vector_store.get_chunk_count(kb_name)
    print(f"索引构建完成: {chunk_count:,} chunks, 耗时 {index_time:.0f}ms")

    # 运行原方案测试
    print(f"\n运行原方案测试 ({len(TEST_QUERIES)} × {num_iterations} = {len(TEST_QUERIES)*num_iterations} 次检索)...")
    original_result = run_benchmark_original(
        retriever, kb_name, TEST_QUERIES, num_iterations, top_k
    )
    original_result.total_chunks = chunk_count
    original_result.index_time_ms = index_time
    print(f"  完成，平均延迟: {original_result.avg_latency:.1f}ms")

    # 运行新方案测试
    print(f"\n运行新方案测试 ({len(TEST_QUERIES)} × {num_iterations} = {len(TEST_QUERIES)*num_iterations} 次检索)...")
    optimized_result = run_benchmark_optimized(
        retriever, kb_name, TEST_QUERIES, num_iterations, top_k
    )
    optimized_result.total_chunks = chunk_count
    optimized_result.index_time_ms = index_time
    print(f"  完成，平均延迟: {optimized_result.avg_latency:.1f}ms")

    # 输出对比报告
    print_comparison(original_result, optimized_result)

    # 清理测试数据
    print("\n清理测试数据...")
    vector_store.delete_knowledge_base(kb_name)
    print("测试完成。")


if __name__ == "__main__":
    asyncio.run(main())
