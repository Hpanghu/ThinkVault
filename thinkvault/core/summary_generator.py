"""
文档摘要生成器 — 使用 LLM 为文档生成摘要
"""

import asyncio

from thinkvault.core import doc_summary_store
from thinkvault.core.container import container
from thinkvault.utils.logger import logger

_SYSTEM_PROMPT = (
    "你是一个文档摘要助手。请为以下文档内容生成一段简洁的中文摘要（200字以内），"
    "涵盖文档的主要主题和关键信息。"
)

_MAX_INPUT_CHARS = 3000


class SummaryGenerator:
    """文档摘要生成器 — 使用 LLM 为文档生成摘要"""

    def generate(self, doc_id: str, raw_text: str, knowledge_base: str) -> str | None:
        """为单个文档生成摘要

        流程：
        1. 截取 raw_text 前 3000 字符作为输入（控制 token 消耗）
        2. 调用 LLM 生成摘要（同步包装异步调用）
        3. 将摘要存入 doc_summary_store
        4. 返回摘要文本
        """
        # 检查是否已有摘要记录
        existing = doc_summary_store.get_by_doc_id(doc_id)
        if existing and existing.get("status") == "generated":
            return existing["summary"]

        # 创建或获取摘要记录
        if existing:
            record_id = existing["id"]
        else:
            record_id = doc_summary_store.add(
                doc_id=doc_id,
                knowledge_base=knowledge_base,
                summary="",
                status="pending",
            )

        # 截取文本
        truncated_text = raw_text[:_MAX_INPUT_CHARS]
        user_prompt = f"请为以下文档生成摘要：\n\n{truncated_text}"

        # 调用 LLM
        try:
            llm = container.thinkvault_llm
            summary_text, _stats = self._run_async(
                llm.generate_async(user_prompt, system_prompt=_SYSTEM_PROMPT)
            )
            if not summary_text or summary_text.startswith("[错误]"):
                doc_summary_store.update_status(record_id, "error")
                logger.warning(f"文档 [{doc_id}] 摘要生成失败: LLM 返回异常")
                return None

            # 保存摘要
            doc_summary_store.update_summary(record_id, summary_text, status="generated")

            # 预计算摘要嵌入并存储（用于分层检索，避免查询时实时计算）
            try:
                summary_emb = container.embedder.embed_single(summary_text)
                if summary_emb is not None:
                    doc_summary_store.update_embedding(record_id, summary_emb)
            except Exception as emb_err:
                logger.debug(f"摘要嵌入计算失败（不影响摘要功能）: {emb_err}")

            logger.info(f"文档 [{doc_id}] 摘要生成成功")
            return summary_text

        except Exception as e:
            logger.error(f"文档 [{doc_id}] 摘要生成异常: {e}")
            try:
                doc_summary_store.update_status(record_id, "error")
            except Exception:
                pass
            return None

    def generate_for_kb(self, knowledge_base: str) -> dict:
        """为知识库中所有 pending 状态的文档批量生成摘要

        流程：
        1. 查询 doc_summary_store.get_by_status(kb, 'pending')
        2. 对每个文档调用 generate()
        3. 返回统计 {"generated": int, "skipped": int, "errors": list}
        """
        pending_docs = doc_summary_store.get_by_status(knowledge_base, "pending")

        generated = 0
        skipped = 0
        errors: list[str] = []

        for doc_record in pending_docs:
            doc_id = doc_record["doc_id"]
            record_id = doc_record["id"]

            # 需要从向量库获取文档原文
            raw_text = self._get_doc_raw_text(doc_id, knowledge_base)
            if not raw_text:
                skipped += 1
                errors.append(doc_id)
                logger.warning(f"跳过文档 [{doc_id}]：无法获取原文")
                continue

            result = self.generate(doc_id, raw_text, knowledge_base)
            if result is not None:
                generated += 1
            else:
                errors.append(doc_id)

        logger.info(
            f"知识库 [{knowledge_base}] 摘要批量生成完成: "
            f"成功 {generated}, 跳过 {skipped}, 失败 {len(errors)}"
        )
        return {"generated": generated, "skipped": skipped, "errors": errors}

    @staticmethod
    def _get_doc_raw_text(doc_id: str, knowledge_base: str) -> str | None:
        """从向量库获取文档的所有 chunk 文本，拼接为完整原文"""
        try:
            collection = container.vector_store.get_or_create_collection(knowledge_base)
            # 通过 doc_id 查找 — chunk ID 格式为 "{source_file}_{chunk_index}"
            # 尝试通过 metadata source_file 过滤
            results = collection.get(
                where={"source_file": doc_id},
                include=["documents"],
            )
            if results and results.get("documents") and results["documents"][0]:
                return "\n".join(results["documents"])

            # 如果 doc_id 不直接匹配 source_file，尝试包含匹配
            all_data = collection.get(include=["metadatas", "documents"])
            if not all_data or not all_data.get("ids"):
                return None

            chunks_text = []
            for i, mid in enumerate(all_data["ids"]):
                metadata = all_data["metadatas"][i] if all_data["metadatas"] else {}
                source = metadata.get("source_file", "")
                if source == doc_id or mid.startswith(f"{doc_id}_"):
                    chunks_text.append(all_data["documents"][i])

            if chunks_text:
                return "\n".join(chunks_text)
            return None
        except Exception as e:
            logger.error(f"获取文档 [{doc_id}] 原文失败: {e}")
            return None

    @staticmethod
    def _run_async(coro):
        """同步包装异步调用，处理事件循环兼容性"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # 已有事件循环运行中（如 FastAPI），用新线程
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        else:
            return asyncio.run(coro)
