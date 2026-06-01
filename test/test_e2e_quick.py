"""
ThinkVault 端到端测试（快速版）— 单问题验证完整链路
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

MODEL_PATH = (
    r"F:\AAone\test\models\Llama\unsloth\Llama-3___2-1B-Instruct-GGUF"
    r"\Llama-3.2-1B-Instruct-Q4_K_M.gguf"
)
TEST_DOC = Path(__file__).parent / "test_doc_deep_learning.txt"
KB_NAME = "e2e_test_v2"

SYSTEM_PROMPT = (
    "你是一个知识渊博的 AI 助手。请根据提供的文档内容回答用户的问题。"
    "如果文档中没有相关内容，请如实说明。用中文回答用户的问题。"
)


def main():
    print("=" * 60)
    print("ThinkVault E2E 快速测试")
    print("=" * 60)

    total_start = time.time()

    # ---- 1. Load LLM ----
    print("\n[1/5] 加载 LLM 模型...")
    from thinkvault.core.container import container

    ok = container.thinkvault_llm.load(MODEL_PATH, n_ctx=2048)
    if not ok:
        print("  ❌ LLM 加载失败"); return
    print("  ✅ OK")

    # ---- 2. Ingest ----
    print("\n[2/5] 摄入文档...")
    from thinkvault.core.parser import DocumentParser
    from thinkvault.core.chunker import TextChunker, ChunkConfig

    doc = DocumentParser.parse(str(TEST_DOC))
    if doc.parse_error:
        print(f"  ❌ 解析失败: {doc.parse_error}"); return
    print(f"  解析: {doc.file_name}, {len(doc.raw_text)} chars")

    chunks = TextChunker(ChunkConfig(chunk_size=512, chunk_overlap=64)).chunk_document(doc)
    print(f"  分块: {len(chunks)} chunks")

    embs = container.embedder.embed([c.text for c in chunks])
    if embs is None:
        print("  ❌ 向量化失败"); return
    print(f"  向量化: {len(embs)} vectors dim={len(embs[0])}")

    container.vector_store.add_chunks(KB_NAME, chunks, embs)
    print(f"  ✅ 摄入完成")

    # ---- 3. Retrieve ----
    question = "ResNet 的核心创新是什么？"
    print(f"\n[3/5] 检索: \"{question}\"")

    hits = container.retriever.retrieve(question, knowledge_base=KB_NAME, top_k=3)
    print(f"  命中: {len(hits)} 条")
    for i, h in enumerate(hits):
        dist = h.get("distance", 0)
        preview = h["text"][:60].replace("\n", " ")
        print(f"  [{i+1}] dist={dist:.4f} \"{preview}...\"")

    if not hits:
        print("  ❌ 无检索结果"); return

    # ---- 4. Build prompt ----
    print("\n[4/5] 组装 prompt...")
    ctx_parts = []
    for i, h in enumerate(hits):
        src = h["metadata"].get("source_file", "?")
        ctx_parts.append(f"--- 片段 {i+1} ({src}) ---\n{h['text']}")
    context = "\n\n".join(ctx_parts)

    prompt = f"""请参考以下文档内容回答问题。如果文档中没有相关信息，请如实说明。

{context}

问题: {question}

回答:"""
    print(f"  上下文 {len(context)} 字符")

    # ---- 5. Generate ----
    print("\n[5/5] LLM 生成 (max_new_tokens=128)...")
    gen_start = time.time()
    answer, stats = container.thinkvault_llm.generate(
        prompt, system_prompt=SYSTEM_PROMPT,
        max_new_tokens=128, temperature=0.7, top_k=50,
    )
    gen_elapsed = time.time() - gen_start

    print(f"\n{'─' * 50}")
    print(f"Q: {question}")
    print(f"A: {answer}")
    print(f"{'─' * 50}")
    print(f"Stats: {stats}")
    print(f"Gen time: {gen_elapsed:.1f}s")

    # ---- Cleanup ----
    container.thinkvault_llm.unload()
    total_elapsed = time.time() - total_start
    print(f"\n总耗时: {total_elapsed:.1f}s")

    # 判定
    if answer and len(answer) > 3:
        print("\n✅ 端到端测试通过")
    else:
        print(f"\n⚠️ 回答过短")


if __name__ == "__main__":
    main()