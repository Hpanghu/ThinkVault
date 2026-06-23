"""
检索系统全面性能评估 — Real Engineers 诊断框架

评估维度：
1. 检索流水线各阶段耗时分解（embed / vector_search / bm25_search / rrf_merge / rerank）
2. 多规模基准（1K / 10K / 50K / 100K / 500K chunks）
3. 并发负载测试（1/4/8/16 并发查询）
4. 冷启动 vs 热启动对比
5. Cross-encoder 重排序开销量化

输出：结构化 JSON 报告 + 控制台摘要
"""

import json
import os
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Optional

# 环境配置
os.environ.pop("THINKVAULT_API_TOKEN", None)
os.environ["THINKVAULT_SKIP_RERANK"] = "1"  # 默认跳过 rerank，单独测试
os.environ["THINKVAULT_BM25_PERSIST"] = "0"  # 避免磁盘 IO 干扰

# ── 中文语料模板 ──────────────────────────────────────────────

CHINESE_TEMPLATES = [
    "量子计算利用量子叠加和纠缠原理，能够在特定问题上实现指数级加速。",
    "深度学习模型的训练过程涉及反向传播算法和梯度下降优化方法。",
    "区块链技术通过分布式账本和共识机制确保数据的不可篡改性。",
    "自然语言处理中的 Transformer 架构彻底改变了序列建模的方式。",
    "微服务架构将单体应用拆分为独立部署的服务，提升了系统的可扩展性。",
    "容器化技术如 Docker 通过操作系统级虚拟化实现了应用的轻量级隔离。",
    "图神经网络在社交网络分析和推荐系统中展现了强大的表达能力。",
    "强化学习通过智能体与环境的交互来学习最优策略，已成功应用于游戏和机器人控制。",
    "联邦学习允许多方在不共享原始数据的情况下协作训练模型，保护数据隐私。",
    "知识图谱将实体和关系组织为图结构，支持复杂的语义推理和问答。",
    "边缘计算将计算资源部署在靠近数据源的位置，减少网络延迟。",
    "数字孪生技术创建物理系统的虚拟副本，用于仿真、监控和优化。",
    "零信任安全模型假设网络内部和外部都不可信，需要持续验证每个访问请求。",
    "大语言模型通过海量文本数据预训练，展现出强大的文本生成和理解能力。",
    "检索增强生成（RAG）将外部知识库与语言模型结合，提升回答的准确性和时效性。",
]

QUERY_TEMPLATES = [
    "量子计算的基本原理是什么？",
    "深度学习模型如何训练？",
    "区块链如何确保数据安全？",
    "Transformer 架构有什么优势？",
    "微服务和单体架构的区别？",
    "Docker 容器化的原理是什么？",
    "图神经网络有哪些应用场景？",
    "强化学习的核心思想是什么？",
    "联邦学习如何保护隐私？",
    "知识图谱支持哪些推理能力？",
    "边缘计算解决了什么问题？",
    "数字孪生技术的应用领域？",
    "零信任安全模型的核心原则？",
    "大语言模型的工作原理？",
    "RAG 技术如何提升问答质量？",
]


@dataclass
class StageTiming:
    """单次检索各阶段耗时（毫秒）"""
    embed_ms: float = 0
    vector_search_ms: float = 0
    bm25_search_ms: float = 0
    rrf_merge_ms: float = 0
    rerank_ms: float = 0
    total_ms: float = 0


@dataclass
class BenchmarkResult:
    """单规模基准测试结果"""
    scale: str = ""
    chunk_count: int = 0
    num_queries: int = 0
    # 总体指标
    avg_ms: float = 0
    p50_ms: float = 0
    p90_ms: float = 0
    p95_ms: float = 0
    p99_ms: float = 0
    max_ms: float = 0
    min_ms: float = 0
    qps: float = 0
    # 各阶段平均耗时
    avg_embed_ms: float = 0
    avg_vector_ms: float = 0
    avg_bm25_ms: float = 0
    avg_rrf_ms: float = 0
    avg_rerank_ms: float = 0
    # 冷启动
    cold_start_ms: float = 0
    # BM25 索引构建时间
    bm25_build_ms: float = 0


@dataclass
class ConcurrencyResult:
    """并发测试结果"""
    concurrency: int = 0
    num_queries: int = 0
    avg_ms: float = 0
    p95_ms: float = 0
    qps: float = 0
    error_count: int = 0


def generate_documents(count: int) -> list[str]:
    """生成指定数量的中文文档片段"""
    docs = []
    for i in range(count):
        base = random.choice(CHINESE_TEMPLATES)
        variation = base + f" 这是第{i}条记录的补充说明，包含了一些额外的上下文信息。"
        docs.append(variation)
    return docs


def percentile(data: list[float], p: float) -> float:
    """计算百分位数"""
    if not data:
        return 0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    idx = min(idx, len(sorted_data) - 1)
    return sorted_data[idx]


def build_test_collection(kb_name: str, chunk_count: int, dim: int = 512):
    """构建测试用向量集合（使用随机嵌入避免真实嵌入计算开销）"""
    import numpy as np
    from thinkvault.core.storage import VectorStore

    vs = VectorStore()
    collection = vs.get_or_create_collection(kb_name)

    # 检查是否已有足够数据
    existing = collection.count()
    if existing >= chunk_count:
        print(f"  [{kb_name}] 已有 {existing} chunks，跳过构建")
        return vs, collection

    # 清空旧数据
    if existing > 0:
        try:
            vs._get_client().delete_collection(vs._safe_name(kb_name))
            collection = vs.get_or_create_collection(kb_name)
        except Exception:
            pass

    print(f"  [{kb_name}] 构建 {chunk_count} chunks 索引...", end=" ", flush=True)
    t0 = time.time()

    docs = generate_documents(chunk_count)
    batch_size = 5000

    for offset in range(0, chunk_count, batch_size):
        batch_docs = docs[offset:offset + batch_size]
        batch_ids = [f"chunk_{offset + i}" for i in range(len(batch_docs))]
        batch_metas = [{"source_file": f"doc_{(offset + i) % 100}.txt"} for i in range(len(batch_docs))]

        # 随机归一化向量（仅用于基准测试，不用于精度评估）
        rng = np.random.default_rng(42 + offset)
        embeddings = rng.standard_normal((len(batch_docs), dim))
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / norms

        collection.add(
            ids=batch_ids,
            documents=batch_docs,
            metadatas=batch_metas,
            embeddings=embeddings.tolist(),
        )

    elapsed = time.time() - t0
    print(f"完成 ({elapsed:.1f}s)")
    return vs, collection


def run_staged_benchmark(retriever, kb_name: str, queries: list[str]) -> list[StageTiming]:
    """运行带阶段计时的基准测试"""
    import numpy as np
    from thinkvault.core.container import container

    results = []
    for query in queries:
        timing = StageTiming()

        # 阶段1: Embedding
        t0 = time.perf_counter()
        query_embedding = container.embedder.embed_single(query)
        timing.embed_ms = (time.perf_counter() - t0) * 1000

        if query_embedding is None:
            timing.total_ms = timing.embed_ms
            results.append(timing)
            continue

        # 阶段2: 向量检索
        t0 = time.perf_counter()
        vector_hits = retriever._vector_search(query, kb_name, 10)
        timing.vector_search_ms = (time.perf_counter() - t0) * 1000

        # 阶段3: BM25 检索
        t0 = time.perf_counter()
        bm25_hits = retriever._bm25_search(query, kb_name, 10)
        timing.bm25_search_ms = (time.perf_counter() - t0) * 1000

        # 阶段4: RRF 融合
        t0 = time.perf_counter()
        merged = retriever._rrf_merge(vector_hits, bm25_hits, top_k=10)
        timing.rrf_merge_ms = (time.perf_counter() - t0) * 1000

        timing.total_ms = timing.embed_ms + timing.vector_search_ms + timing.bm25_search_ms + timing.rrf_merge_ms
        results.append(timing)

    return results


def run_scale_benchmark(scale_name: str, chunk_count: int, num_queries: int = 50) -> BenchmarkResult:
    """运行单规模的完整基准测试"""
    from thinkvault.core.retriever import Retriever
    from thinkvault.core.container import container

    kb_name = f"bench_{scale_name}"
    result = BenchmarkResult(scale=scale_name, chunk_count=chunk_count, num_queries=num_queries)

    # 构建测试数据
    vs, collection = build_test_collection(kb_name, chunk_count)
    actual_count = collection.count()
    result.chunk_count = actual_count

    # 初始化检索器
    retriever = Retriever()

    # 确保嵌入模型已加载
    if not container.embedder.is_loaded:
        print(f"  加载嵌入模型...", end=" ", flush=True)
        t0 = time.time()
        container.embedder.load()
        print(f"完成 ({time.time() - t0:.1f}s)")

    # 冷启动测试（首次 BM25 构建）
    test_query = random.choice(QUERY_TEMPLATES)
    t0 = time.perf_counter()
    try:
        retriever.retrieve(test_query, kb_name, top_k=5)
    except Exception:
        pass
    result.cold_start_ms = (time.perf_counter() - t0) * 1000

    # BM25 构建时间（清除缓存后测量）
    retriever.invalidate_cache(kb_name)
    t0 = time.perf_counter()
    retriever._get_bm25(kb_name)
    result.bm25_build_ms = (time.perf_counter() - t0) * 1000

    # 热启动基准测试（带阶段计时）
    queries = random.choices(QUERY_TEMPLATES, k=num_queries)
    stage_timings = run_staged_benchmark(retriever, kb_name, queries)

    total_times = [t.total_ms for t in stage_timings]
    wall_start = time.perf_counter()
    for query in queries:
        try:
            retriever.retrieve(query, kb_name, top_k=5)
        except Exception:
            pass
    wall_elapsed = time.perf_counter() - wall_start

    result.avg_ms = statistics.mean(total_times) if total_times else 0
    result.p50_ms = percentile(total_times, 50)
    result.p90_ms = percentile(total_times, 90)
    result.p95_ms = percentile(total_times, 95)
    result.p99_ms = percentile(total_times, 99)
    result.max_ms = max(total_times) if total_times else 0
    result.min_ms = min(total_times) if total_times else 0
    result.qps = num_queries / wall_elapsed if wall_elapsed > 0 else 0

    # 各阶段平均
    result.avg_embed_ms = statistics.mean([t.embed_ms for t in stage_timings])
    result.avg_vector_ms = statistics.mean([t.vector_search_ms for t in stage_timings])
    result.avg_bm25_ms = statistics.mean([t.bm25_search_ms for t in stage_timings])
    result.avg_rrf_ms = statistics.mean([t.rrf_merge_ms for t in stage_timings])

    # 清理
    retriever.invalidate_cache(kb_name)

    return result


def run_concurrency_test(kb_name: str, chunk_count: int, concurrency_levels: list[int],
                          queries_per_level: int = 40) -> list[ConcurrencyResult]:
    """并发负载测试"""
    from thinkvault.core.retriever import Retriever
    from thinkvault.core.container import container

    results = []

    # 确保数据存在
    build_test_collection(kb_name, chunk_count)

    if not container.embedder.is_loaded:
        container.embedder.load()

    # 预热（使用共享 Retriever 实例，避免并发测试中重复构建 BM25 索引）
    shared_retriever = Retriever()
    shared_retriever.retrieve("测试查询", kb_name, top_k=5)

    for conc in concurrency_levels:
        cr = ConcurrencyResult(concurrency=conc, num_queries=queries_per_level)
        queries = random.choices(QUERY_TEMPLATES, k=queries_per_level)

        latencies = []
        errors = 0

        def single_query_shared(q: str) -> float:
            """使用共享 Retriever 实例执行查询（线程安全）"""
            t0 = time.perf_counter()
            try:
                shared_retriever.retrieve(q, kb_name, top_k=5)
            except Exception:
                return -1
            return (time.perf_counter() - t0) * 1000

        wall_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=conc) as pool:
            futures = [pool.submit(single_query_shared, q) for q in queries]
            for f in as_completed(futures):
                lat = f.result()
                if lat < 0:
                    errors += 1
                else:
                    latencies.append(lat)
        wall_elapsed = time.perf_counter() - wall_start

        if latencies:
            cr.avg_ms = statistics.mean(latencies)
            cr.p95_ms = percentile(latencies, 95)
        cr.qps = queries_per_level / wall_elapsed if wall_elapsed > 0 else 0
        cr.error_count = errors
        results.append(cr)

    return results


def run_rerank_overhead_test(kb_name: str, chunk_count: int, num_queries: int = 20) -> dict:
    """量化 Cross-encoder 重排序开销"""
    from thinkvault.core.retriever import Retriever
    from thinkvault.core.container import container

    build_test_collection(kb_name, chunk_count)

    if not container.embedder.is_loaded:
        container.embedder.load()

    # 不带 rerank
    os.environ["THINKVAULT_SKIP_RERANK"] = "1"
    retriever = Retriever()
    queries = random.choices(QUERY_TEMPLATES, k=num_queries)

    times_no_rerank = []
    for q in queries:
        t0 = time.perf_counter()
        retriever.retrieve(q, kb_name, top_k=5)
        times_no_rerank.append((time.perf_counter() - t0) * 1000)

    # 带 rerank（尝试加载 cross-encoder）
    os.environ["THINKVAULT_SKIP_RERANK"] = "0"
    retriever2 = Retriever()
    cross_encoder = retriever2._get_cross_encoder()

    if cross_encoder is None:
        os.environ["THINKVAULT_SKIP_RERANK"] = "1"
        return {
            "rerank_available": False,
            "avg_without_rerank_ms": statistics.mean(times_no_rerank),
            "note": "Cross-encoder 模型不可用，无法测试 rerank 开销",
        }

    times_with_rerank = []
    for q in queries:
        t0 = time.perf_counter()
        retriever2.retrieve(q, kb_name, top_k=5)
        times_with_rerank.append((time.perf_counter() - t0) * 1000)

    os.environ["THINKVAULT_SKIP_RERANK"] = "1"

    return {
        "rerank_available": True,
        "avg_without_rerank_ms": statistics.mean(times_no_rerank),
        "avg_with_rerank_ms": statistics.mean(times_with_rerank),
        "rerank_overhead_ms": statistics.mean(times_with_rerank) - statistics.mean(times_no_rerank),
        "rerank_overhead_pct": (statistics.mean(times_with_rerank) / statistics.mean(times_no_rerank) - 1) * 100,
    }


def print_scale_report(results: list[BenchmarkResult]):
    """打印规模基准测试报告"""
    print("\n" + "=" * 90)
    print("检索性能基准测试报告 — 多规模对比")
    print("=" * 90)

    header = f"{'规模':<10} {'Chunks':>8} {'平均(ms)':>10} {'P50(ms)':>10} {'P95(ms)':>10} {'P99(ms)':>10} {'最大(ms)':>10} {'QPS':>8}"
    print(header)
    print("-" * 90)

    for r in results:
        row = f"{r.scale:<10} {r.chunk_count:>8} {r.avg_ms:>10.1f} {r.p50_ms:>10.1f} {r.p95_ms:>10.1f} {r.p99_ms:>10.1f} {r.max_ms:>10.1f} {r.qps:>8.1f}"
        print(row)

    # 阶段耗时分解
    print("\n" + "-" * 90)
    print("检索流水线阶段耗时分解（平均，毫秒）")
    print("-" * 90)
    stage_header = f"{'规模':<10} {'Embed':>10} {'Vector':>10} {'BM25':>10} {'RRF':>10} {'冷启动':>10} {'BM25构建':>10}"
    print(stage_header)
    print("-" * 90)

    for r in results:
        row = f"{r.scale:<10} {r.avg_embed_ms:>10.1f} {r.avg_vector_ms:>10.1f} {r.avg_bm25_ms:>10.1f} {r.avg_rrf_ms:>10.1f} {r.cold_start_ms:>10.1f} {r.bm25_build_ms:>10.1f}"
        print(row)

    # 阶段占比
    print("\n" + "-" * 90)
    print("阶段耗时占比（%）")
    print("-" * 90)
    pct_header = f"{'规模':<10} {'Embed':>10} {'Vector':>10} {'BM25':>10} {'RRF':>10}"
    print(pct_header)
    print("-" * 90)

    for r in results:
        total = r.avg_embed_ms + r.avg_vector_ms + r.avg_bm25_ms + r.avg_rrf_ms
        if total > 0:
            row = f"{r.scale:<10} {r.avg_embed_ms/total*100:>9.1f}% {r.avg_vector_ms/total*100:>9.1f}% {r.avg_bm25_ms/total*100:>9.1f}% {r.avg_rrf_ms/total*100:>9.1f}%"
            print(row)


def print_concurrency_report(results: list[ConcurrencyResult]):
    """打印并发测试报告"""
    print("\n" + "=" * 70)
    print("并发负载测试报告")
    print("=" * 70)

    header = f"{'并发数':>8} {'查询数':>8} {'平均(ms)':>10} {'P95(ms)':>10} {'QPS':>10} {'错误':>6}"
    print(header)
    print("-" * 70)

    for r in results:
        row = f"{r.concurrency:>8} {r.num_queries:>8} {r.avg_ms:>10.1f} {r.p95_ms:>10.1f} {r.qps:>10.1f} {r.error_count:>6}"
        print(row)


def main():
    # 可通过命令行参数控制测试规模
    quick_mode = "--quick" in sys.argv
    full_mode = "--full" in sys.argv

    if quick_mode:
        scales = [("1K", 1000), ("10K", 10000)]
        num_queries = 20
        concurrency_levels = [1, 4]
    elif full_mode:
        scales = [("1K", 1000), ("10K", 10000), ("50K", 50000), ("100K", 100000), ("500K", 500000)]
        num_queries = 100
        concurrency_levels = [1, 4, 8, 16, 32]
    else:
        scales = [("1K", 1000), ("10K", 10000), ("50K", 50000)]
        num_queries = 50
        concurrency_levels = [1, 4, 8, 16]

    print("ThinkVault 检索系统全面性能评估")
    print(f"测试规模: {[s[0] for s in scales]}")
    print(f"每规模查询数: {num_queries}")
    print(f"并发级别: {concurrency_levels}")
    print()

    # ── 1. 多规模基准测试 ──
    print("=" * 50)
    print("阶段 1: 多规模基准测试")
    print("=" * 50)

    scale_results = []
    for scale_name, chunk_count in scales:
        print(f"\n--- 规模: {scale_name} ({chunk_count} chunks) ---")
        result = run_scale_benchmark(scale_name, chunk_count, num_queries)
        scale_results.append(result)
        print(f"  平均: {result.avg_ms:.1f}ms | P95: {result.p95_ms:.1f}ms | QPS: {result.qps:.1f}")

    print_scale_report(scale_results)

    # ── 2. 并发负载测试 ──
    print("\n" + "=" * 50)
    print("阶段 2: 并发负载测试")
    print("=" * 50)

    conc_kb = f"bench_conc"
    conc_chunks = 50000
    conc_results = run_concurrency_test(conc_kb, conc_chunks, concurrency_levels, queries_per_level=40)
    print_concurrency_report(conc_results)

    # ── 3. Rerank 开销量化 ──
    print("\n" + "=" * 50)
    print("阶段 3: Cross-encoder 重排序开销")
    print("=" * 50)

    rerank_result = run_rerank_overhead_test("bench_rerank", 10000, num_queries=20)
    print(f"\n  Rerank 可用: {rerank_result['rerank_available']}")
    if rerank_result['rerank_available']:
        print(f"  无 rerank 平均: {rerank_result['avg_without_rerank_ms']:.1f}ms")
        print(f"  有 rerank 平均: {rerank_result['avg_with_rerank_ms']:.1f}ms")
        print(f"  Rerank 开销: +{rerank_result['rerank_overhead_ms']:.1f}ms ({rerank_result['rerank_overhead_pct']:.1f}%)")
    else:
        print(f"  无 rerank 平均: {rerank_result['avg_without_rerank_ms']:.1f}ms")
        print(f"  {rerank_result['note']}")

    # ── 4. 输出 JSON 报告 ──
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "config": {
            "scales": [s[0] for s in scales],
            "num_queries": num_queries,
            "concurrency_levels": concurrency_levels,
        },
        "scale_benchmarks": [asdict(r) for r in scale_results],
        "concurrency_benchmarks": [asdict(r) for r in conc_results],
        "rerank_analysis": rerank_result,
    }

    report_path = os.path.join(os.path.dirname(__file__), "retrieval_perf_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n完整报告已保存: {report_path}")


if __name__ == "__main__":
    main()
