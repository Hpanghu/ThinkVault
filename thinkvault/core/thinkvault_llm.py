"""
ThinkVault LLM 集成模块 — OpenAI 兼容 API 模式

基于 httpx 调用外部推理后端（Ollama / OpenAI / 兼容 API），
将 HTTP SSE 流式响应封装为与旧 gguf-chat 接口一致的 async 生成器。

ThinkVault 专注 RAG（文档解析→检索→上下文组装），推理交给标准 OpenAI API。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional, List, Tuple, Dict, Any

import httpx

from thinkvault.utils.logger import logger

# ---------------------------------------------------------------------------
# Chat 模板（可选，部分后端需要）
# ---------------------------------------------------------------------------

CHAT_TEMPLATE = (
    "<|begin_of_text|>"
    "<|start_header_id|>system<|end_header_id|>\n\n{system}<|eot_id|>"
    "<|start_header_id|>user<|end_header_id|>\n\n{user}<|eot_id|>"
    "<|start_header_id|>assistant<|end_header_id|>\n\n"
)


def format_chat_prompt(system: str, user: str) -> str:
    """使用 Llama 3.2 Chat 模板组装 prompt（兼容需要完整 prompt 字符串的后端）"""
    return CHAT_TEMPLATE.format(system=system, user=user)


# ---------------------------------------------------------------------------
# ThinkVault LLM — OpenAI 兼容 API 模式
# ---------------------------------------------------------------------------

class ThinkVaultLLM:
    """基于 httpx 的 OpenAI 兼容 API 推理器

    默认后端: Ollama (http://localhost:11434/v1)
    支持任意兼容 OpenAI Chat Completions API 的服务。
    """

    def __init__(self, base_url: str = "http://localhost:11434/v1", model: str = "llama3.2:1b", api_key: Optional[str] = None):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()
        self._is_available: bool = False

    # ---- 属性 ----

    @property
    def is_loaded(self) -> bool:
        """后端是否可用（通过 GET /v1/models 探测）"""
        return self._is_available

    @property
    def model(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        return self._base_url

    # ---- 加载 / 卸载 ----

    def load(self, model_path: str = "", n_ctx: int = 2048) -> bool:
        """保留空方法（HTTP 后端无需本地加载），返回 True 以兼容容器接口"""
        logger.info("OpenAI 兼容模式：无需本地加载模型，load() 为无操作")
        return True

    def unload(self):
        """保留空方法（HTTP 后端无需本地卸载），返回 True 以兼容容器接口"""
        logger.info("OpenAI 兼容模式：无需卸载模型，unload() 为无操作")
        pass

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 httpx.AsyncClient 单例（异步锁保护并发安全）。

        检测到旧 client 已关闭（如调用方多次 asyncio.run() 导致事件循环切换）
        时自动重建。"""
        if self._client is not None and not self._client.is_closed:
            return self._client
        async with self._client_lock:
            # 双重检查：安全关闭已失效的旧 client（避免在已关闭事件循环上引用）
            if self._client is not None:
                try:
                    await self._client.aclose()
                except Exception:
                    pass
                self._client = None

            if self._client is None:
                headers = {}
                if self._api_key:
                    headers["Authorization"] = f"Bearer {self._api_key}"
                self._client = httpx.AsyncClient(
                    base_url=self._base_url,
                    headers=headers,
                    timeout=httpx.Timeout(30.0, connect=3.0),
                )
        return self._client

    async def close(self) -> None:
        """关闭持久化 httpx 客户端，释放连接池资源

        容错处理：若事件循环已关闭（如多次 asyncio.run() 场景），
        则直接丢弃 client 引用而不尝试 aclose，避免 RuntimeError。
        """
        if self._client is not None:
            client = self._client
            self._client = None
            if not client.is_closed:
                try:
                    await client.aclose()
                except RuntimeError:
                    # 事件循环已关闭，无法正常 aclose，安全丢弃引用
                    pass
                except Exception:
                    pass
            logger.info("ThinkVaultLLM HTTP 客户端已关闭")

    async def _check_availability(self) -> bool:
        """通过 GET /v1/models 检查后端可用性"""
        try:
            client = await self._get_client()
            # Ollama 兼容端点：GET /api/tags 或 GET /v1/models
            # 优先尝试 OpenAI 标准端点
            resp = await client.get("/v1/models", timeout=3.0)
            if resp.status_code == 200:
                self._is_available = True
                return True
        except Exception:
            pass

        # 尝试 Ollama 原生端点
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(self._base_url.replace("/v1", "") + "/api/tags")
                if resp.status_code == 200:
                    self._is_available = True
                    return True
        except Exception:
            pass

        self._is_available = False
        return False

    # ---- 推理核心 ----

    async def generate(
        self,
        messages: List[Dict[str, str]],
        *,
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        top_k: int = 50,
    ) -> Tuple[str, dict]:
        """非流式生成回答

        Args:
            messages: OpenAI Chat 格式消息列表 [{"role": "...", "content": "..."}]
            max_new_tokens: 最大生成 token 数
            temperature: 温度参数
            top_k: top_k 采样参数（部分后端支持）

        Returns:
            (生成的文本, 统计信息 dict)
        """
        t0 = time.time()
        url = f"{self._base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_new_tokens,
            "temperature": temperature,
            "stream": False,
        }
        # 部分后端支持 top_k
        if top_k > 0:
            payload["top_k"] = top_k

        try:
            client = await self._get_client()
            try:
                resp = await client.post(url, headers=headers, json=payload)
            except RuntimeError as e:
                if "Event loop is closed" in str(e):
                    # httpx client 绑定到已关闭的事件循环 → 丢弃并重建
                    self._client = None
                    client = await self._get_client()
                    resp = await client.post(url, headers=headers, json=payload)
                else:
                    raise
            resp.raise_for_status()
            data = resp.json()

            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            elapsed = time.time() - t0

            stats = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "elapsed_sec": round(elapsed, 2),
                "tokens_per_sec": round(output_tokens / elapsed, 1) if elapsed > 0 else 0,
            }
            return text.strip(), stats

        except httpx.ConnectError:
            logger.error("连接推理后端失败，请确认 Ollama 是否运行")
            return (
                "[错误] 无法连接推理后端，请确认 Ollama 已安装并运行：\n"
                "  1. 安装 Ollama: https://ollama.com/download\n"
                "  2. 拉取模型: ollama pull llama3.2:1b\n"
                "  3. 启动 Ollama（默认监听 http://localhost:11434）",
                {"error": "connection_refused"},
            )
        except Exception as e:
            logger.error(f"LLM 推理异常: {e}")
            return f"[错误] 推理异常: {e}", {"error": str(e)}

    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        *,
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        top_k: int = 50,
    ):
        """流式生成器 — SSE 逐 token yield

        Yields:
            dict: {"token": str, "done": bool, "stats": dict | None}
        """
        url = f"{self._base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_new_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if top_k > 0:
            payload["top_k"] = top_k

        t0 = time.time()
        full_text = ""
        input_tokens = 0
        output_tokens = 0

        try:
            client = await self._get_client()
            try:
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk["choices"][0].get("delta", {})
                            token = delta.get("content", "")
                            if token:
                                full_text += token
                                yield {"token": token, "done": False, "stats": None}

                            # 有些后端在 chunk 中返回 usage
                            usage = chunk.get("usage", {})
                            if usage:
                                input_tokens = usage.get("prompt_tokens", input_tokens)
                                output_tokens = usage.get("completion_tokens", output_tokens)
                        except (json.JSONDecodeError, KeyError):
                            continue
            except RuntimeError as e:
                if "Event loop is closed" in str(e):
                    self._client = None
                    client = await self._get_client()
                    async with client.stream("POST", url, headers=headers, json=payload) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                delta = chunk["choices"][0].get("delta", {})
                                token = delta.get("content", "")
                                if token:
                                    full_text += token
                                    yield {"token": token, "done": False, "stats": None}
                                usage = chunk.get("usage", {})
                                if usage:
                                    input_tokens = usage.get("prompt_tokens", input_tokens)
                                    output_tokens = usage.get("completion_tokens", output_tokens)
                            except (json.JSONDecodeError, KeyError):
                                continue
                else:
                    raise

        except httpx.ConnectError:
            logger.error("连接推理后端失败，请确认 Ollama 是否运行")
            yield {
                "token": (
                    "[错误] 无法连接推理后端，请确认 Ollama 已安装并运行：\n"
                    "  1. 安装 Ollama: https://ollama.com/download\n"
                    "  2. 拉取模型: ollama pull llama3.2:1b\n"
                    "  3. 启动 Ollama（默认监听 http://localhost:11434）"
                ),
                "done": True,
                "stats": {"error": "connection_refused"},
            }
            return
        except Exception as e:
            logger.error(f"LLM 流式推理异常: {e}")
            yield {"token": f"[错误] 推理异常: {e}", "done": True, "stats": {"error": str(e)}}
            return

        elapsed = time.time() - t0
        stats = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "elapsed_sec": round(elapsed, 2),
            "tokens_per_sec": round(output_tokens / elapsed, 1) if elapsed > 0 and output_tokens > 0 else 0,
        }
        yield {"token": "", "done": True, "stats": stats}

    # ---- Async 接口（兼容旧接口） ----

    async def generate_async(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        top_k: int = 50,
    ) -> Tuple[str, dict]:
        """异步生成回答（兼容旧接口）

        将 prompt + system_prompt 组装为 messages 列表后调用 generate()。
        """
        messages = _build_messages(system_prompt, [], prompt)
        return await self.generate(
            messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_k=top_k,
        )

    async def generate_stream_async(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        top_k: int = 50,
    ):
        """异步流式生成器（兼容旧接口）

        将 prompt + system_prompt 组装为 messages 列表后调用 generate_stream()。
        """
        messages = _build_messages(system_prompt, [], prompt)
        async for chunk in self.generate_stream(
            messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_k=top_k,
        ):
            yield chunk


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _build_messages(system_prompt: str, conversation_history: List[Dict[str, str]], user_message: str) -> List[Dict[str, str]]:
    """将 system_prompt + conversation_history + user_message 组装为 OpenAI Chat 格式

    Returns:
        [{"role": "...", "content": "..."}, ...]
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for msg in conversation_history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if content:
            messages.append({"role": role, "content": content})
    if user_message:
        messages.append({"role": "user", "content": user_message})
    return messages


# ---------------------------------------------------------------------------
# 全局单例已移除 — 请通过 container.get("thinkvault_llm") 或 container.thinkvault_llm 获取实例
# ---------------------------------------------------------------------------
