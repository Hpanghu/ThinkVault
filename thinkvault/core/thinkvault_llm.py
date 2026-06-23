"""
ThinkVault LLM 集成模块 — OpenAI 兼容 API 模式

基于 httpx 调用外部推理后端（llama-cpp-python server / OpenAI / 兼容 API），
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
from thinkvault.utils.security import validate_url_for_ssrf


class LLMServiceError(Exception):
    """LLM 服务调用异常"""
    def __init__(self, message: str, error_type: str = "unknown"):
        super().__init__(message)
        self.error_type = error_type

# ---------------------------------------------------------------------------
# ThinkVault LLM — OpenAI 兼容 API 模式
# ---------------------------------------------------------------------------

class ThinkVaultLLM:
    """基于 httpx 的 OpenAI 兼容 API 推理器

    默认后端: llama-cpp-python server (http://localhost:8080/v1)
    支持任意兼容 OpenAI Chat Completions API 的服务。
    """

    def __init__(self, base_url: str = "http://localhost:8080/v1", model: str = "default", api_key: Optional[str] = None):
        try:
            safe_url = validate_url_for_ssrf(base_url)
            self._base_url = safe_url.rstrip("/")
        except ValueError as e:
            logger.warning(f"SSRF 防护拒绝 base_url: {base_url}，使用默认值")
            self._base_url = "http://localhost:8080/v1"
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
                    logger.debug("关闭旧 httpx 客户端失败", exc_info=True)
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

    async def _recover_client(self, error: RuntimeError) -> None:
        """事件循环关闭时重建 httpx 客户端

        当 httpx client 绑定到已关闭的事件循环时，丢弃旧引用并重建新客户端，
        使后续 _get_client() 调用自动获取有效客户端。
        """
        if "Event loop is closed" in str(error):
            logger.warning("检测到事件循环关闭，重建 HTTP 客户端")
            self._client = None
            await self._get_client()
        else:
            raise

    async def reconfigure(self, base_url: str = "", model: str = "", api_key: str = "") -> None:
        """更新 LLM 客户端配置（base_url / model / api_key），关闭旧客户端使下次请求自动重建"""
        updated = False
        if base_url and base_url != self._base_url:
            try:
                safe_url = validate_url_for_ssrf(base_url)
                self._base_url = safe_url.rstrip("/")
                updated = True
            except ValueError as e:
                logger.warning(f"SSRF 防护拒绝 base_url: {base_url}，忽略此更新")
        if model:
            self._model = model
            updated = True
        if api_key != self._api_key:
            self._api_key = api_key or None
            updated = True
        if updated:
            # 关闭旧客户端，下次 _get_client() 会用新配置重建
            await self.close()
            self._is_available = False

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
                    logger.debug("关闭 httpx 客户端时事件循环已关闭", exc_info=True)
                except Exception:
                    logger.debug("关闭 httpx 客户端失败", exc_info=True)
            logger.info("ThinkVaultLLM HTTP 客户端已关闭")

    # ---- 可用性状态管理（公共接口） ----

    def mark_unavailable(self) -> None:
        """标记后端不可用（供外部调用方使用）"""
        self._is_available = False

    def mark_available(self) -> None:
        """标记后端可用"""
        self._is_available = True

    def is_backend_available(self) -> bool:
        """检查后端是否可用（公共接口）"""
        return self._is_available

    async def check_availability(self) -> bool:
        """通过 GET /models 检查后端可用性（公共接口，封装 _check_availability）"""
        return await self._check_availability()

    async def _check_availability(self) -> bool:
        """通过 GET /models 检查后端可用性（base_url 已含 /v1 前缀，使用相对路径）"""
        try:
            client = await self._get_client()
            # 使用相对路径 "models"，httpx 会解析为 base_url + "/models"
            # 例如 base_url="http://localhost:8080/v1" → "http://localhost:8080/v1/models"
            resp = await client.get("models", timeout=3.0)
            if resp.status_code == 200:
                self._is_available = True
                return True
        except Exception:
            logger.debug("检查 LLM 后端可用性失败", exc_info=True)

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
                await self._recover_client(e)
                client = await self._get_client()
                resp = await client.post(url, headers=headers, json=payload)
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
            logger.error("连接推理后端失败，请确认 llama-cpp-python server 是否运行")
            raise LLMServiceError(
                "无法连接推理后端，请确认 llama-cpp-python server 已安装并运行",
                error_type="connection_refused",
            )
        except Exception as e:
            logger.error(f"LLM 推理异常: {e}")
            raise LLMServiceError(f"推理异常: {e}", error_type="inference_error") from e

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

        async def _stream_with_client(client: httpx.AsyncClient):
            """使用指定客户端执行流式请求，yield 每个 token chunk"""
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
                            yield {"token": token, "done": False, "stats": None}
                        # 有些后端在 chunk 中返回 usage
                        usage = chunk.get("usage", {})
                        if usage:
                            yield {"_input_tokens": usage.get("prompt_tokens", 0), "_output_tokens": usage.get("completion_tokens", 0)}
                    except (json.JSONDecodeError, KeyError):
                        continue

        try:
            client = await self._get_client()
            try:
                async for item in _stream_with_client(client):
                    if "_input_tokens" in item:
                        input_tokens = item["_input_tokens"]
                        output_tokens = item["_output_tokens"]
                    elif item.get("token"):
                        full_text += item["token"]
                        yield item
            except RuntimeError as e:
                await self._recover_client(e)
                client = await self._get_client()
                async for item in _stream_with_client(client):
                    if "_input_tokens" in item:
                        input_tokens = item["_input_tokens"]
                        output_tokens = item["_output_tokens"]
                    elif item.get("token"):
                        full_text += item["token"]
                        yield item

        except httpx.ConnectError:
            logger.error("连接推理后端失败，请确认 llama-cpp-python server 是否运行")
            yield {
                "token": "[错误] 无法连接推理后端，请确认服务已启动",
                "done": True,
                "stats": {"error": "connection_refused"},
            }
            return
        except LLMServiceError:
            raise
        except Exception as e:
            logger.error(f"LLM 流式推理异常: {e}")
            raise LLMServiceError(f"流式推理异常: {e}", error_type="stream_error") from e

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
