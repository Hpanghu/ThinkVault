"""聊天路由 — SSE 流式推理 + 非流式聊天 + 检索降级 + 多角色支持"""

import json
import traceback
import asyncio
import unicodedata

from fastapi import APIRouter, HTTPException

from thinkvault.core.container import container
from thinkvault.core import conversation_store as conv_store
from thinkvault.core.role_store import role_store
from thinkvault.core.thinkvault_llm import _build_messages, LLMServiceError
from thinkvault.core.inline_summarizer import inline_summarizer
from thinkvault.config import ensure_builtin_roles, get_default_role_id
from thinkvault.utils.logger import logger

from thinkvault.api.schemas import ChatRequest, ChatResponse

chat_router = APIRouter()

DEFAULT_SYSTEM_PROMPT = (
    "用中文回答用户的问题。仅基于提供的文档内容回答，"
    "如果文档中没有相关信息请如实说明。"
)


def _get_role_for_conversation(conv_id: str) -> dict:
    """获取会话关联的角色"""
    conv = conv_store.get_conversation(conv_id)
    if not conv:
        return {}

    role_id = conv.get("role_id", "")
    if role_id:
        role = role_store.get_role(role_id)
        if role:
            return role

    return {}


def _get_system_prompt(role: dict, custom_prompt: str = "") -> str:
    """获取系统提示词（优先使用自定义，然后角色，最后默认）"""
    if custom_prompt:
        return custom_prompt
    if role and role.get("system_prompt"):
        return role["system_prompt"]
    return DEFAULT_SYSTEM_PROMPT


def _get_role_name(role: dict) -> str:
    """获取角色名称"""
    return role.get("name", "知识馆长")


def _build_context(message: str, kb: str):
    """构建检索上下文。使用 retriever 的 should_retrieve 进行意图判断。"""
    context = ""
    sources = []
    hits = []
    if container.retriever.should_retrieve(message, kb):
        hits = container.retriever.retrieve(message, knowledge_base=kb, top_k=5)
        context, sources = container.retriever.format_context(hits)
    return context, sources, hits


async def _build_context_async(message: str, kb: str):
    """异步构建检索上下文"""
    return await asyncio.to_thread(_build_context, message, kb)


def _assemble_user_message(message: str, context: str, role: dict = None) -> str:
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


def _generate_clarification(message: str, role: dict) -> str:
    """根据角色风格生成澄清追问"""
    role_name = _get_role_name(role)
    clarifications = {
        "知识馆长": f"请明确您所指的内容。为了更精准地为您定位文献，请提供更多上下文信息，例如：\n\n- 相关的文件名或主题关键词\n- 您想了解的具体方面\n- 任何相关的上下文描述\n\n期待您的进一步说明。",
        "技术导师": f"让我们先澄清一下您的问题。为了更好地帮助您学习，请提供更多信息：\n\n- 您遇到的具体问题是什么？\n- 您尝试过哪些方法？\n- 您期望达到什么效果？\n\n请告诉我更多细节，我们一起解决这个问题！",
        "创意助手": f"这个想法很有意思！不过我还不太确定您指的是什么。能不能告诉我更多呢？\n\n- 您想到的具体场景是什么？\n- 您有哪些灵感来源？\n- 您希望实现什么样的效果？\n\n让我们一起探索更多可能性！",
    }
    return clarifications.get(role_name, f"为了更好地帮助您，请提供更多关于「{message}」的上下文信息。")


def _run_retrieval_only(message: str, kb: str, role: dict = None) -> ChatResponse:
    """仅检索模式：模型未加载时，返回检索到的文档片段及来源。"""
    return ChatResponse(
        answer="推理后端未连接。请先启动 Ollama 服务后重试。",
        sources=[],
        mode="retrieval_only",
    )


@chat_router.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """非流式聊天 — 推理后端不可用时自动降级为仅检索模式"""
    ensure_builtin_roles()

    if not container.thinkvault_llm.is_loaded:
        await container.thinkvault_llm.check_availability()
    if not container.thinkvault_llm.is_backend_available():
        resp = _run_retrieval_only(req.message, req.knowledge_base)
        if req.conversation_id:
            conv_store.add_message(req.conversation_id, "user", req.message)
            conv_store.add_message(req.conversation_id, "assistant", resp.answer)
            resp.conversation_id = req.conversation_id
        return resp

    try:
        role = {}
        conv_id = req.conversation_id

        if conv_id:
            role = _get_role_for_conversation(conv_id)
        elif req.role_id:
            role = role_store.get_role(req.role_id) or {}

        intent_result = container.retriever._classify_intent(req.message, req.knowledge_base)

        if intent_result["intent_type"] == "ambiguous":
            clarification = _generate_clarification(req.message, role)

            if not conv_id:
                role_id = req.role_id or get_default_role_id()
                conv = await asyncio.to_thread(conv_store.create_conversation, title=_make_title(req.message), role_id=role_id)
                conv_id = conv["id"]

            await asyncio.to_thread(conv_store.add_message, conv_id, "user", req.message)
            await asyncio.to_thread(conv_store.add_message, conv_id, "assistant", clarification)

            return ChatResponse(
                answer=clarification,
                sources=[],
                conversation_id=conv_id,
                mode="clarification",
            )

        context, sources, hits = await _build_context_async(req.message, req.knowledge_base)
        user_content = _assemble_user_message(req.message, context, role)
        system = _get_system_prompt(role, req.system_prompt)

        messages = _build_messages(system, [], user_content)

        answer, stats = await container.thinkvault_llm.generate(
            messages,
            max_new_tokens=512, temperature=0.7, top_k=50,
        )

        if not conv_id:
            role_id = req.role_id or get_default_role_id()
            conv = await asyncio.to_thread(conv_store.create_conversation, title=_make_title(req.message), role_id=role_id)
            conv_id = conv["id"]

            if role and role.get("welcome_message"):
                await asyncio.to_thread(conv_store.add_message, conv_id, "assistant", role["welcome_message"])

        await asyncio.to_thread(conv_store.add_message, conv_id, "user", req.message)
        await asyncio.to_thread(conv_store.add_message, conv_id, "assistant", answer)

        conv = await asyncio.to_thread(conv_store.get_conversation, conv_id)
        if conv and conv["title"] == _make_title(req.message) and answer.strip():
            await asyncio.to_thread(conv_store.update_conversation, conv_id, title=answer.strip()[:30])

        return ChatResponse(
            answer=answer, sources=sources, stats=stats,
            conversation_id=conv_id, mode="chat",
        )
    except LLMServiceError as e:
        logger.error(f"LLM 服务异常: {e}")
        return ChatResponse(
            answer=f"[错误] {e}", sources=[],
            stats={"error": e.error_type}, mode="chat",
        )
    except Exception as e:
        logger.error(f"聊天失败: {e}\n{traceback.format_exc()}")
        return ChatResponse(
            answer="[错误] 服务内部异常，请稍后重试", sources=[],
            stats={"error": "internal_error"}, mode="chat",
        )


@chat_router.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE 流式聊天 — 推理后端不可用时自动降级为仅检索模式"""
    ensure_builtin_roles()

    if not container.thinkvault_llm.is_loaded:
        await container.thinkvault_llm.check_availability()
    if not container.thinkvault_llm.is_backend_available():
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

    role = {}
    conv_id = req.conversation_id

    if conv_id:
        role = _get_role_for_conversation(conv_id)
    elif req.role_id:
        role = role_store.get_role(req.role_id) or {}

    intent_result = container.retriever._classify_intent(req.message, req.knowledge_base)

    if intent_result["intent_type"] == "ambiguous":
        clarification = _generate_clarification(req.message, role)

        if not conv_id:
            role_id = req.role_id or get_default_role_id()
            conv = await asyncio.to_thread(conv_store.create_conversation, title=_make_title(req.message), role_id=role_id)
            conv_id = conv["id"]

        await asyncio.to_thread(conv_store.add_message, conv_id, "user", req.message)
        await asyncio.to_thread(conv_store.add_message, conv_id, "assistant", clarification)

        payload = json.dumps({
            "token": clarification, "done": True,
            "stats": {}, "sources": [],
            "conversation_id": conv_id, "mode": "clarification",
        }, ensure_ascii=False)

        async def clarification_chunk():
            yield f"data: {payload}\n\n"

        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            clarification_chunk(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    context, sources, hits = await _build_context_async(req.message, req.knowledge_base)
    user_content = _assemble_user_message(req.message, context, role)
    system = _get_system_prompt(role, req.system_prompt)

    if not conv_id:
        role_id = req.role_id or get_default_role_id()
        conv = await asyncio.to_thread(conv_store.create_conversation, title=_make_title(req.message), role_id=role_id)
        conv_id = conv["id"]

    await asyncio.to_thread(conv_store.add_message, conv_id, "user", req.message)

    messages = _build_messages(system, [], user_content)

    async def sse_generator():
        full_answer = ""
        summary_inserted = False

        try:
            if hits and len(hits) > 0:
                role_name = _get_role_name(role)
                summary = inline_summarizer.summarize_chunks(hits, req.message, role_name)
                if summary:
                    yield f"data: {json.dumps({'token': summary + '\\n\\n', 'done': False, 'stats': None, 'mode': 'chat'}, ensure_ascii=False)}\n\n"
                    summary_inserted = True

            async for chunk in container.thinkvault_llm.generate_stream(
                messages,
                max_new_tokens=512, temperature=0.7, top_k=50,
            ):
                if chunk["done"]:
                    await asyncio.to_thread(conv_store.add_message, conv_id, "assistant", full_answer)
                    conv = await asyncio.to_thread(conv_store.get_conversation, conv_id)
                    if conv and conv["title"] == _make_title(req.message) and full_answer.strip():
                        await asyncio.to_thread(conv_store.update_conversation, conv_id, title=full_answer.strip()[:30])
                    yield f"data: {json.dumps({'token':'','done':True,'stats':chunk.get('stats'),'sources':sources,'conversation_id':conv_id,'mode':'chat'}, ensure_ascii=False)}\n\n"
                    break
                token_text = chunk["token"]
                full_answer += token_text
                yield f"data: {json.dumps({'token':token_text,'done':False,'stats':None,'mode':'chat'}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0)
        except LLMServiceError as e:
            logger.error(f"SSE LLM 服务异常: {e}")
            yield f"data: {json.dumps({'token':'[错误] 推理服务异常','done':True,'stats':{'error':e.error_type},'mode':'chat'}, ensure_ascii=False)}\n\n"
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
