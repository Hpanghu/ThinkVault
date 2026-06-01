"""
补充测试：LLM 模块 — 客户端/关闭/检查可用性/生成路径
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock


# ── 初始化 ────────────────────────────────────────────────────

def test_init_with_custom_params():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    llm = ThinkVaultLLM(
        base_url="https://api.openai.com/v1",
        model="gpt-4",
        api_key="sk-test"
    )
    assert llm.base_url == "https://api.openai.com/v1"
    assert llm.model == "gpt-4"
    assert llm.is_loaded is False

    # trailing slash stripped
    llm2 = ThinkVaultLLM(base_url="http://localhost:11434/v1/")
    assert llm2.base_url == "http://localhost:11434/v1"


# ── _build_messages ──────────────────────────────────────────

def test_build_messages_no_system():
    from thinkvault.core.thinkvault_llm import _build_messages
    msgs = _build_messages("", [], "hello")
    assert len(msgs) == 1
    assert msgs[0] == {"role": "user", "content": "hello"}


def test_build_messages_no_user():
    from thinkvault.core.thinkvault_llm import _build_messages
    msgs = _build_messages("sys", [], "")
    assert len(msgs) == 1
    assert msgs[0] == {"role": "system", "content": "sys"}


def test_build_messages_both_empty():
    from thinkvault.core.thinkvault_llm import _build_messages
    msgs = _build_messages("", [], "")
    assert msgs == []


def test_build_messages_history_with_empty_content():
    from thinkvault.core.thinkvault_llm import _build_messages
    history = [{"role": "user", "content": ""}, {"role": "assistant", "content": None}]
    msgs = _build_messages("sys", history, "hello")
    # 空 content 被过滤
    assert len(msgs) == 2  # system + user


# ── close ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_close_no_client():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    llm = ThinkVaultLLM()
    await llm.close()  # 空 client 不抛异常
    assert llm._client is None


@pytest.mark.asyncio
async def test_close_with_client():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    llm = ThinkVaultLLM()
    mock_client = AsyncMock()
    mock_client.is_closed = False
    llm._client = mock_client
    await llm.close()
    mock_client.aclose.assert_awaited_once()
    assert llm._client is None


@pytest.mark.asyncio
async def test_close_runtime_error_tolerated():
    """close 时 RuntimeError (事件循环关闭) 不崩溃"""
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    llm = ThinkVaultLLM()
    mock_client = AsyncMock()
    mock_client.is_closed = False
    mock_client.aclose.side_effect = RuntimeError("Event loop is closed")
    llm._client = mock_client
    await llm.close()
    assert llm._client is None


@pytest.mark.asyncio
async def test_close_generic_error_tolerated():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    llm = ThinkVaultLLM()
    mock_client = AsyncMock()
    mock_client.is_closed = False
    mock_client.aclose.side_effect = Exception("random")
    llm._client = mock_client
    await llm.close()
    assert llm._client is None


# ── _check_availability ──────────────────────────────────────

@pytest.mark.asyncio
async def test_check_availability_success():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    llm = ThinkVaultLLM()
    mock_client = AsyncMock()
    mock_client.is_closed = False
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_client.get.return_value = mock_resp
    llm._client = mock_client

    result = await llm._check_availability()
    assert result is True
    assert llm._is_available is True


@pytest.mark.asyncio
async def test_check_availability_fails_both():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    llm = ThinkVaultLLM()
    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("connection refused")
    llm._client = mock_client

    result = await llm._check_availability()
    assert result is False
    assert llm._is_available is False


# ── generate 错误路径 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_connect_error():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    import httpx

    llm = ThinkVaultLLM()
    with patch.object(llm, "_get_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError(
            "All connection attempts failed"
        )
        mock_get.return_value = mock_client

        text, stats = await llm.generate([{"role": "user", "content": "test"}])
        assert "[错误]" in text
        assert "connection_refused" in stats.get("error", "")


@pytest.mark.asyncio
async def test_generate_general_error():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM

    llm = ThinkVaultLLM()
    with patch.object(llm, "_get_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.post.side_effect = ValueError("unexpected format")
        mock_get.return_value = mock_client

        text, stats = await llm.generate([{"role": "user", "content": "test"}])
        assert "[错误]" in text
        assert "unexpected format" in stats.get("error", "")


# ── generate_stream 错误路径 ─────────────────────────────────

@pytest.mark.asyncio
async def test_generate_stream_connect_error():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    import httpx

    llm = ThinkVaultLLM()

    async def raise_connect_error():
        raise httpx.ConnectError("All connection attempts failed")

    with patch.object(llm, "_get_client", new=raise_connect_error):
        results = []
        async for chunk in llm.generate_stream([{"role": "user", "content": "test"}]):
            results.append(chunk)

        assert len(results) == 1
        assert results[0]["done"] is True
        assert "[错误]" in results[0]["token"]
        assert "connection_refused" in results[0]["stats"].get("error", "")


@pytest.mark.asyncio
async def test_generate_stream_general_error():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM

    llm = ThinkVaultLLM()
    with patch.object(llm, "_get_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.stream.side_effect = KeyError("missing field")
        mock_get.return_value = mock_client

        results = []
        async for chunk in llm.generate_stream([{"role": "user", "content": "test"}]):
            results.append(chunk)

        assert results[0]["done"] is True
        assert "[错误]" in results[0]["token"]


# ── generate_async / generate_stream_async 兼容接口 ─────────

@pytest.mark.asyncio
async def test_generate_async_wraps_generate():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM

    llm = ThinkVaultLLM()
    with patch.object(llm, "generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = ("answer", {"elapsed_sec": 0.5})
        text, stats = await llm.generate_async("你好", system_prompt="你是助手")
        mock_gen.assert_awaited_once()

        messages = mock_gen.call_args[0][0]
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"


@pytest.mark.asyncio
async def test_generate_stream_async_wraps_stream():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM

    llm = ThinkVaultLLM()
    mock_stream = AsyncMock()
    mock_stream.__aiter__.return_value = [
        {"token": "你", "done": False, "stats": None},
        {"token": "好", "done": False, "stats": None},
        {"token": "", "done": True, "stats": {"elapsed_sec": 0.5}},
    ]
    with patch.object(llm, "generate_stream", return_value=mock_stream):
        chunks = []
        async for c in llm.generate_stream_async("你好"):
            chunks.append(c)
        assert len(chunks) == 3
        assert chunks[0]["token"] == "你"


# ── 属性 ─────────────────────────────────────────────────────

def test_properties():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    llm = ThinkVaultLLM()
    assert llm.model == "llama3.2:1b"
    assert llm.base_url == "http://localhost:11434/v1"


# ── format_chat_prompt ───────────────────────────────────────

def test_format_chat_prompt_empty():
    from thinkvault.core.thinkvault_llm import format_chat_prompt
    prompt = format_chat_prompt("", "")
    assert "<|begin_of_text|>" in prompt
    assert "<|start_header_id|>system<|end_header_id|>" in prompt
    assert "<|start_header_id|>user<|end_header_id|>" in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--asyncio-mode=auto"])