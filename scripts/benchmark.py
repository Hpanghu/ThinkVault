"""
ThinkVault 性能基准测试脚本
对 chunk → embed → retrieve 链路进行基准测试
"""

import sys
import time
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def format_elapsed(start: float) -> str:
    elapsed = time.perf_counter() - start
    if elapsed < 1:
        return f"{elapsed*1000:.1f}ms"
    return f"{elapsed:.2f}s"


# ════════════════════════════════════════════════════
#  1. Chunk 基准
# ════════════════════════════════════════════════════

def benchmark_chunk(text_length: int = 10000):
    """基准：文本分块"""
    from thinkvault.core.chunker import TextChunker, ChunkConfig

    md_content = (
        "# Heading\n\nThis is paragraph content.\n\n"
        "## Subheading\n\nMore content here.\n\n"
    ) * (text_length // 100)

    print(f"\n{'='*60}")
    print("  Benchmark: Chunk")
    print(f"  Input: {len(md_content)} chars")
    print(f"{'='*60}")

    config = ChunkConfig(chunk_size=512, chunk_overlap=64)
    chunker = TextChunker(config)

    # Simple mock parsed document
    parsed_doc = type('obj', (), {
        'paragraphs': [{'text': md_content, 'page': 1, 'char_count': len(md_content)}]
    })()

    t0 = time.perf_counter()
    chunks = chunker.chunk_document(parsed_doc)
    t1 = time.perf_counter()

    print(f"  Chunks: {len(chunks)}")
    print(f"  Time:   {format_elapsed(t0)}")
    print(f"  Rate:   {len(md_content)/(t1-t0):.0f} chars/sec")

    avg_len = sum(len(getattr(c, 'text', str(c))) for c in chunks) / max(len(chunks), 1)
    print(f"  Avg chunk len: {avg_len:.0f} chars")


# ════════════════════════════════════════════════════
#  3. Retrieve 基准
# ════════════════════════════════════════════════════

def benchmark_retrieve(kb_name: str = "benchmark_kb"):
    """基准：检索链路"""
    from thinkvault.core.retriever import Retriever

    queries = [
        "knowledge management system",
        "hybrid retrieval vector search",
        "OpenAI compatible API",
        "document chunking ChromaDB",
        "SSE streaming tokens",
    ]

    print(f"\n{'='*60}")
    print("  Benchmark: Retrieve")
    print(f"  KB: {kb_name}")
    print(f"  Queries: {len(queries)}")
    print(f"{'='*60}")

    retriever = Retriever()

    times = []
    for q in queries:
        t0 = time.perf_counter()
        hits = retriever.retrieve(q, kb_name, top_k=5)
        elapsed = time.perf_counter() - t0
        times.append(elapsed)
        print(f"  [{len(hits)} hits] ({elapsed*1000:.0f}ms) \"{q[:45]}...\"")

    if times:
        avg = sum(times) / len(times)
        print(f"\n  Avg: {avg*1000:.1f}ms | Min: {min(times)*1000:.1f}ms | Max: {max(times)*1000:.1f}ms")


# ════════════════════════════════════════════════════
#  4. Embed 基准
# ════════════════════════════════════════════════════

def benchmark_embed():
    """基准：Embedding 生成"""
    from thinkvault.core.embedder import Embedder

    texts = [
        "ThinkVault is a personal knowledge management system.",
        "Hybrid retrieval combines vector search and BM25.",
        "OpenAI-compatible API backends are supported.",
        "Documents are chunked and stored in ChromaDB.",
        "SSE streaming enables real-time token generation.",
    ] * 3

    print(f"\n{'='*60}")
    print("  Benchmark: Embed")
    print(f"  Texts: {len(texts)}")
    print(f"{'='*60}")

    embedder = Embedder()

    t0 = time.perf_counter()
    loaded = embedder.load()
    print(f"  Load:   {format_elapsed(t0)} success={loaded}")

    if not loaded:
        print("  [SKIP] Embedder not available")
        return

    t0 = time.perf_counter()
    embeddings = embedder.embed(texts)
    t1 = time.perf_counter()

    if embeddings:
        dim = len(embeddings[0])
        print(f"  Embed:  {format_elapsed(t0)}")
        print(f"  Dims:   {dim}")
        print(f"  Rate:   {len(texts)/(t1-t0):.1f} texts/sec")


# ════════════════════════════════════════════════════
#  5. LLM 基准
# ════════════════════════════════════════════════════

def benchmark_llm():
    """基准：LLM 推理"""
    import asyncio
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM

    print(f"\n{'='*60}")
    print("  Benchmark: LLM (generate)")
    print(f"{'='*60}")

    async def _run():
        llm = ThinkVaultLLM()
        available = await llm._check_availability()
        if not available:
            print("  [SKIP] LLM backend not available")
            return

        for max_tok in [10, 50, 100]:
            messages = [{"role": "user", "content": "Explain what a vector database is in 2 sentences."}]
            t0 = time.perf_counter()
            text, stats = await llm.generate(messages, max_new_tokens=max_tok)
            elapsed = time.perf_counter() - t0
            print(f"  max_tok={max_tok:3d} | {elapsed*1000:.0f}ms | {len(text)} chars | {stats.get('tokens_per_sec', 0):.1f} tok/s")

        await llm.close()

    asyncio.run(_run())


# ════════════════════════════════════════════════════
#  Main
# ════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="ThinkVault Benchmark Suite")
    parser.add_argument("--all", action="store_true", help="Run all benchmarks")
    parser.add_argument("--chunk", action="store_true")
    parser.add_argument("--embed", action="store_true")
    parser.add_argument("--retrieve", action="store_true")
    parser.add_argument("--llm", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=10000, help="Input text size (chars)")
    parser.add_argument("--kb", default="benchmark_kb", help="KB for retrieve benchmark")

    args = parser.parse_args()

    if not any([args.all, args.chunk, args.embed, args.retrieve, args.llm]):
        parser.print_help()
        return

    print("ThinkVault v2.0.0 Benchmark Suite")
    print(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')} | Platform: {sys.platform}")

    if args.all or args.chunk:
        benchmark_chunk(text_length=args.chunk_size)
    if args.all or args.embed:
        benchmark_embed()
    if args.all or args.retrieve:
        benchmark_retrieve(kb_name=args.kb)
    if args.all or args.llm:
        benchmark_llm()

    print(f"\n{'='*60}")
    print("  Benchmark Complete")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()