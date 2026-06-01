"""聊天路由 — SSE 流式推理 + 非流式聊天 + 检索降级"""

import json
import traceback
import asyncio
import unicodedata

from fastapi import APIRouter, HTTPException

from thinkvault.core.container import container
from thinkvault.core import conversation_store as conv_store
from thinkvault.core.thinkvault_llm import _build_messages
from thinkvault.utils.logger import logger

from thinkvault.api.schemas import ChatRequest, ChatResponse

chat_router = APIRouter()

SYSTEM_PROMPT = (
    "用中文回答用户的问题。仅基于提供的文档内容回答，"
    "如果文档中没有相关信息请如实说明。"
)


def _build_context(message: str, kb: str):
    """构建检索上下文。使用 retriever 的 should_retrieve 进行意图判断。"""
    context = ""
    sources = []
    if container.retriever.should_retrieve(message, kb):
        hits = container.retriever.retrieve(message, knowledge_base=kb, top_k=5)
        context, sources = container.retriever.format_context(hits)
    return context, sources


def _assemble_user_message(message: str, context: str) -> str:
    """将检索上下文拼入用户消息，返回最终的 user content 字符串"""
    if context:
        return f"参考以下文档内容回答问题：\n\n{context}\n\n---\n\n问题：{message}"
    return message


def _make_title(message: str) -> str:
    if len(message) <= 30:
        return message
    result = message[:30]
    while result and unicodedata.category(result[-1]) in ("Mn", "Mc", "Sk"):
        result = result[:-1]
    if not result.strip():
        return "Chat"
    return result + "..."


# ── 检索降级模式 ──────────────────────────────────────────────────

def _run_retrieval_only(message: str, kb: str) -> ChatResponse:
    """仅检索模式：模型未加载时，返回检索到的文档片段及来源。
    
    不使用 embedder 向量检索，直接返回提示信息，避免同步加载阻塞事件循环。
    """
    return ChatResponse(
        answer="推理后端未连接。请先启动 Ollama 服务后重试。",
        sources=[],
        mode="retrieval_only",
    )


# ── 聊天接口 ──────────────────────────────────────────────────────

@chat_router.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """非流式聊天 — 推理后端不可用时自动降级为仅检索模式"""
    # 检查后端可用性（首次调用时探测）
    if not container.thinkvault_llm.is_loaded:
        await container.thinkvault_llm._check_availability()
    if not container.thinkvault_llm.is_loaded:
        resp = _run_retrieval_only(req.message, req.knowledge_base)
        # 降级模式下仍持久化消息到会话
        if req.conversation_id:
            conv_store.add_message(req.conversation_id, "user", req.message)
            conv_store.add_message(req.conversation_id, "assistant", resp.answer)
            resp.conversation_id = req.conversation_id
        return resp

    try:
        context, sources = _build_context(req.message, req.knowledge_base)
        user_content = _assemble_user_message(req.message, context)
        system = req.system_prompt or SYSTEM_PROMPT

        messages = _build_messages(system, [], user_content)

        answer, stats = await container.thinkvault_llm.generate(
            messages,
            max_new_tokens=512, temperature=0.7, top_k=50,
        )

        conv_id = req.conversation_id
        if not conv_id:
            conv = conv_store.create_conversation(title=_make_title(req.message))
            conv_id = conv["id"]

        conv_store.add_message(conv_id, "user", req.message)
        conv_store.add_message(conv_id, "assistant", answer)

        conv = conv_store.get_conversation(conv_id)
        if conv and conv["title"] == _make_title(req.message) and answer.strip():
            conv_store.update_conversation(conv_id, title=answer.strip()[:30])

        return ChatResponse(
            answer=answer, sources=sources, stats=stats,
            conversation_id=conv_id, mode="chat",
        )
    except Exception as e:
        logger.error(f"聊天失败: {e}\n{traceback.format_exc()}")
        return ChatResponse(
            answer="[错误] 服务内部异常，请稍后重试", sources=[],
            stats={"error": "internal_error"}, mode="chat",
        )


@chat_router.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE 流式聊天 — 推理后端不可用时自动降级为仅检索模式（非流式返回）"""
    # 检查后端可用性
    if not container.thinkvault_llm.is_loaded:
        await container.thinkvault_llm._check_availability()
    if not container.thinkvault_llm.is_loaded:
        retrieval_resp = _run_retrieval_only(req.message, req.knowledge_base)
        payload = json.dumps({
            "token": retrieval_resp.answer, "done": True,
            "stats": retrieval_resp.stats, "sources": retrieval_resp.sources,
            "conversation_id": None, "mode": "retrieval_only",
        }, ensure_ascii=False)

        async def single_chunk():
            yield f"data: {payload}\n\n"

        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            single_chunk(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    context, sources = _build_context(req.message, req.knowledge_base)
    user_content = _assemble_user_message(req.message, context)
    system = req.system_prompt or SYSTEM_PROMPT

    conv_id = req.conversation_id
    if not conv_id:
        conv = conv_store.create_conversation(title=_make_title(req.message))
        conv_id = conv["id"]

    conv_store.add_message(conv_id, "user", req.message)

    messages = _build_messages(system, [], user_content)

    async def sse_generator():
        full_answer = ""
        try:
            async for chunk in container.thinkvault_llm.generate_stream(
                messages,
                max_new_tokens=512, temperature=0.7, top_k=50,
            ):
                if chunk["done"]:
                    conv_store.add_message(conv_id, "assistant", full_answer)
                    conv = conv_store.get_conversation(conv_id)
                    if conv and conv["title"] == _make_title(req.message) and full_answer.strip():
                        conv_store.update_conversation(conv_id, title=full_answer.strip()[:30])
                    yield f"data: {json.dumps({'token':'','done':True,'stats':chunk.get('stats'),'sources':sources,'conversation_id':conv_id,'mode':'chat'}, ensure_ascii=False)}\n\n"
                    break
                token_text = chunk["token"]
                full_answer += token_text
                yield f"data: {json.dumps({'token':token_text,'done':False,'stats':None,'mode':'chat'}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0)
        except Exception as e:
            logger.error(f"SSE 流异常: {e}")
            yield f"data: {json.dumps({'token':'[错误] 服务内部异常','done':True,'stats':{'error':'internal_error'},'mode':'chat'}, ensure_ascii=False)}\n\n"

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
