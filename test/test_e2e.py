"""
ThinkVault 端到端测试：文档摄入 → 向量检索 → LLM 生成回答

测试链路：
  1. 加载 Llama 3.2 1B Q4_K_M GGUF 模型
  2. 解析/分块/向量化测试文档
  3. 用户提问 → 检索相关片段 → 组装 prompt → LLM 生成回答
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# 加载 .env 环境变量（E2E 测试不经过 FastAPI lifespan）
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

# ---- 模型路径 ----
_PROJECT_ROOT = Path(__file__).parent.parent
MODEL_PATH = (
    _PROJECT_ROOT / "test" / "models" / "Llama" / "unsloth"
    / "Llama-3___2-1B-Instruct-GGUF" / "Llama-3.2-1B-Instruct-Q4_K_M.gguf"
)

# ---- 测试文档 ----
TEST_DOC = Path(__file__).parent / "test_doc_deep_learning.txt"

# ---- 知识库名称 ----
KB_NAME = "e2e_test"

# ---- 系统提示词 ----
SYSTEM_PROMPT = (
    "你是一个知识渊博的 AI 助手。请根据提供的文档内容回答用户的问题。"
    "如果文档中没有相关内容，请如实说明。用中文回答用户的问题。"
)


def load_llm():
    """步骤 1：初始化 LLM 后端"""
    import asyncio
    from thinkvault.core.container import container

    print("\n[1/5] 初始化 LLM 后端...")
    llm = container.thinkvault_llm
    llm.load()  # 兼容容器接口

    # 探测后端可用性
    async def _probe():
        return await llm._check_availability()

    if asyncio.run(_probe()):
        print(f"  ✅ LLM 后端已就绪: {llm.model}")
        return llm
    else:
        print("  ❌ LLM 后端不可用，请确保 Ollama 已运行")
        return None


def ingest_document():
    """步骤 2：解析 → 分块 → 向量化 → 存储"""
    from thinkvault.core.parser import DocumentParser
    from thinkvault.core.chunker import TextChunker, ChunkConfig
    from thinkvault.core.container import container

    print("\n[2/5] 摄入测试文档...")

    # 解析
    doc = DocumentParser.parse(str(TEST_DOC))
    if doc.parse_error:
        print(f"  ❌ 解析失败: {doc.parse_error}")
        return None
    print(f"  - 解析完成: {doc.file_name} ({doc.file_type}), {len(doc.raw_text)} 字符")

    # 分块
    chunker = TextChunker(ChunkConfig(chunk_size=512, chunk_overlap=64))
    chunks = chunker.chunk_document(doc)
    print(f"  - 分块完成: {len(chunks)} 个块")

    # 向量化
    embeddings = container.embedder.embed([c.text for c in chunks])
    if embeddings is None:
        print("  ❌ 向量化失败")
        return None
    print(f"  - 向量化完成: {len(embeddings)} 个向量 (dim={len(embeddings[0])})")

    # 存储
    count = container.vector_store.add_chunks(KB_NAME, chunks, embeddings)
    print(f"  - 存储完成: {count} 个块已索引到知识库 [{KB_NAME}]")

    return chunks


def search(query: str, top_k: int = 3):
    """步骤 3：检索相关片段"""
    from thinkvault.core.container import container

    print(f"\n[3/5] 检索: \"{query}\"")
    hits = container.retriever.retrieve(query, knowledge_base=KB_NAME, top_k=top_k)
    print(f"  - 找到 {len(hits)} 个相关片段")

    for i, h in enumerate(hits):
        src = h["metadata"].get("source_file", "?")
        dist = h.get("distance", 0)
        preview = h["text"][:80].replace("\n", " ")
        print(f"    [{i+1}] {src}  dist={dist:.4f}  \"{preview}...\"")

    return hits


def build_qa_messages(hits, question: str) -> list:
    """步骤 4：组装 RAG 消息"""
    print("\n[4/5] 组装上下文...")

    context_parts = []
    for i, h in enumerate(hits):
        src = h["metadata"].get("source_file", "未知")
        context_parts.append(f"--- 文档片段 {i+1} (来源: {src}) ---\n{h['text']}")

    context = "\n\n".join(context_parts)

    user_msg = f"""请参考以下文档内容回答问题。如果文档中没有相关信息，请如实说明"文档中未提及"。

{context}

问题: {question}"""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    print(f"  - 上下文长度: {len(context)} 字符")
    return messages


def generate_answer(llm, messages: list):
    """步骤 5：LLM 生成回答"""
    import asyncio

    print("\n[5/5] LLM 生成回答...")

    async def _run():
        return await llm.generate(messages, max_new_tokens=256, temperature=0.7, top_k=50)

    answer, stats = asyncio.run(_run())

    print(f"  - 输入 tokens: {stats.get('input_tokens', '?')}")
    print(f"  - 输出 tokens: {stats.get('output_tokens', '?')}")
    print(f"  - 耗时: {stats.get('elapsed_sec', '?')}s")
    print(f"  - 速度: {stats.get('tokens_per_sec', '?')} tok/s")

    return answer, stats


def _run_basic_completion_test(llm):
    """附加测试：简单中文补全"""
    import asyncio

    print("\n" + "=" * 60)
    print("附加测试：简单中文问答（不用文档）")
    print("=" * 60)

    messages = [
        {"role": "system", "content": "用中文回答用户的问题。回答应简洁明了。"},
        {"role": "user", "content": "请简单介绍一下什么是机器学习？"},
    ]

    async def _run():
        return await llm.generate(messages, max_new_tokens=128, temperature=0.7, top_k=50)

    answer, stats = asyncio.run(_run())

    print(f"\n  Q: 什么是机器学习？")
    print(f"  A: {answer}")
    print(f"  Stats: {stats}")
    return answer


def main():
    print("=" * 60)
    print("ThinkVault 端到端测试")
    print("=" * 60)
    print(f"  模型: {MODEL_PATH}")
    print(f"  文档: {TEST_DOC.name}")
    print(f"  知识库: {KB_NAME}")

    total_start = time.time()
    results = {"pass": 0, "fail": 0, "details": []}

    # ---- Step 1: Load LLM ----
    llm = load_llm()
    if llm is None:
        results["fail"] += 1
        results["details"].append("LLM 加载失败")
        print("\n❌ 端到端测试失败：无法加载模型")
        return results
    results["pass"] += 1

    # ---- Step 2: Ingest ----
    chunks = ingest_document()
    if chunks is None:
        results["fail"] += 1
        results["details"].append("文档摄入失败")
        print("\n❌ 端到端测试失败：文档摄入失败")
        return results
    results["pass"] += 1

    # ---- Step 3: Search ----
    questions = [
        "什么是卷积神经网络？",
        "ResNet 的核心创新是什么？",
        "Transformer 架构有什么特点？",
    ]

    for q in questions:
        hits = search(q, top_k=3)
        if not hits:
            results["fail"] += 1
            results["details"].append(f"检索无结果: {q}")
            print(f"  ❌ 检索失败: 无相关结果")
            continue
        results["pass"] += 1

        # ---- Step 4 & 5: QA ----
        messages = build_qa_messages(hits, q)
        answer, stats = generate_answer(llm, messages)

        print(f"\n  {'─' * 50}")
        print(f"  Q: {q}")
        print(f"  A: {answer}")
        print(f"  Stats: {stats}")

        # 简单验证：回答不为空且不太短
        if answer and len(answer) > 5:
            results["pass"] += 1
        else:
            results["fail"] += 1
            results["details"].append(f"回答过短或为空: {q}")

    # ---- 附加测试 ----
    _run_basic_completion_test(llm)

    # ---- Step 6: Cleanup ----
    print("\n[6/6] E2E 测试完成\n")

    total_elapsed = time.time() - total_start

    # ---- 测试报告 ----
    print("\n" + "=" * 60)
    print("测试报告")
    print("=" * 60)
    print(f"  总耗时: {total_elapsed:.1f}s")
    print(f"  通过: {results['pass']}")
    print(f"  失败: {results['fail']}")
    if results["details"]:
        print("  失败详情:")
        for d in results["details"]:
            print(f"    - {d}")

    if results["fail"] == 0:
        print("\n✅ 端到端测试全部通过")
    else:
        print(f"\n⚠️ 端到端测试部分失败 ({results['fail']} 项)")

    return results


if __name__ == "__main__":
    main()
