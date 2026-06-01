"""
扩展测试：thinkvault_llm.py 覆盖率从 66% → 80%+
补充：is_loaded True、_check_availability Ollama 回退、generate 成功、
generate_stream 成功路径、generate_async/stream_async、close 兜底
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock


# ── is_loaded True ───────────────────────────────────────────

def test_is_loaded_when_available():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    llm = ThinkVaultLLM()
    llm._is_available = True
    assert llm.is_loaded is True


# ── _check_availability Ollama 回退 ──────────────────────────

@pytest.mark.asyncio
async def test_check_availability_v1_fails_ollama_succeeds():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    import httpx

    llm = ThinkVaultLLM()
    mock_client = AsyncMock()
    mock_client.is_closed = False
    mock_resp_fail = MagicMock()
    mock_resp_fail.status_code = 500
    mock_resp_fail.text = ""
    mock_resp_fail.raise_for_status.side_effect = httpx.HTTPStatusError(
        "fail", request=MagicMock(), response=mock_resp_fail)
    mock_client.get.return_value = mock_resp_fail
    llm._client = mock_client

    ollama_resp = MagicMock()
    ollama_resp.status_code = 200
    ollama_client = MagicMock()
    ollama_client.__aenter__ = AsyncMock(return_value=ollama_client)
    ollama_client.__aexit__ = AsyncMock(return_value=None)
    ollama_client.is_closed = False
    ollama_client.get = AsyncMock(return_value=ollama_resp)

    with patch.object(httpx, 'AsyncClient', return_value=ollama_client):
        result = await llm._check_availability()
    assert result is True




# ── generate 成功路径 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_success():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    llm = ThinkVaultLLM()
    with patch.object(llm, "_get_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "  Hello World  "}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_client.post.return_value = mock_resp
        mock_get.return_value = mock_client

        text, stats = await llm.generate(
            [{"role": "user", "content": "hi"}],
            max_new_tokens=128, temperature=0.5, top_k=40,
        )
        assert text == "Hello World"
        assert stats["input_tokens"] == 10
        assert stats["output_tokens"] == 5
        assert stats["total_tokens"] == 15
        assert "elapsed_sec" in stats


@pytest.mark.asyncio
async def test_generate_top_k_zero():
    """top_k=0 时不传 top_k 参数"""
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    llm = ThinkVaultLLM()
    with patch.object(llm, "_get_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }
        mock_client.post.return_value = mock_resp
        mock_get.return_value = mock_client

        text, stats = await llm.generate([{"role": "user", "content": "test"}], top_k=0)
        assert text == "ok"


# ── generate_stream ────────────────────────────────────────


class FakeStreamResponse:
    """模拟 httpx stream 响应"""

    def __init__(self, lines):
        self._lines = lines
        self.status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for line in self._lines:
            yield line


@pytest.mark.asyncio
async def test_generate_stream_success():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    import httpx
    llm = ThinkVaultLLM()

    fake_resp = FakeStreamResponse([
        'data: {"choices":[{"delta":{"content":"你好"}}]}',
        'data: {"choices":[{"delta":{"content":"世界"}}]}',
        'data: [DONE]',
    ])

    with patch.object(httpx.AsyncClient, 'stream', return_value=fake_resp):
        with patch.object(llm, "_get_client") as mock_get:
            client = httpx.AsyncClient()
            mock_get.return_value = client
            tokens = []
            async for chunk in llm.generate_stream([{"role": "user", "content": "hi"}]):
                tokens.append(chunk["token"])
            assert "".join(tokens) == "你好世界"


@pytest.mark.asyncio
async def test_generate_stream_with_usage():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    import httpx
    llm = ThinkVaultLLM()

    fake_resp = FakeStreamResponse([
        'data: {"choices":[{"delta":{"content":"OK"}}],"usage":{"prompt_tokens":5,"completion_tokens":2}}',
        'data: [DONE]',
    ])

    with patch.object(httpx.AsyncClient, 'stream', return_value=fake_resp):
        with patch.object(llm, "_get_client") as mock_get:
            client = httpx.AsyncClient()
            mock_get.return_value = client
            results = [chunk async for chunk in llm.generate_stream([{"role": "user", "content": "x"}])]
            assert results[-1]["done"] is True
            assert results[-1]["stats"]["input_tokens"] == 5


@pytest.mark.asyncio
async def test_generate_stream_json_error():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    import httpx
    llm = ThinkVaultLLM()

    fake_resp = FakeStreamResponse([
        'data: garbage-not-json',
        'data: {"choices":[{"delta":{"content":"valid"}}]}',
        'data: [DONE]',
    ])

    with patch.object(httpx.AsyncClient, 'stream', return_value=fake_resp):
        with patch.object(llm, "_get_client") as mock_get:
            client = httpx.AsyncClient()
            mock_get.return_value = client
            tokens = []
            async for chunk in llm.generate_stream([{"role": "user", "content": "x"}]):
                if chunk["token"] and not chunk["done"]:
                    tokens.append(chunk["token"])
            assert "valid" in "".join(tokens)


# ── generate_async 兼容接口 ─────────────────────────────────

@pytest.mark.asyncio
async def test_generate_async_with_system():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    llm = ThinkVaultLLM()
    with patch.object(llm, "generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = ("response", {"elapsed_sec": 1.0})
        text, stats = await llm.generate_async(
            "question", system_prompt="You are helpful",
            max_new_tokens=512, temperature=0.3, top_k=50,
        )
        mock_gen.assert_awaited_once()
        msgs = mock_gen.call_args[0][0]
        assert msgs[0] == {"role": "system", "content": "You are helpful"}


@pytest.mark.asyncio
async def test_generate_stream_async():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    llm = ThinkVaultLLM()

    async def fake_gen(messages, **kwargs):
        yield {"token": "a", "done": False, "stats": None}
        yield {"token": "", "done": True, "stats": {"elapsed_sec": 0.5}}

    with patch.object(llm, "generate_stream", side_effect=fake_gen):
        chunks = [c async for c in llm.generate_stream_async("prompt", system_prompt="sys")]
        assert chunks[0]["token"] == "a"


# ── close 已关闭 client ─────────────────────────────────────

@pytest.mark.asyncio
async def test_close_already_closed_client():
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    llm = ThinkVaultLLM()
    mock_client = AsyncMock()
    mock_client.is_closed = True
    llm._client = mock_client
    await llm.close()
    mock_client.aclose.assert_not_awaited()


# ── format_chat_prompt 边界 ─────────────────────────────────

def test_format_chat_prompt_special_chars():
    from thinkvault.core.thinkvault_llm import format_chat_prompt
    prompt = format_chat_prompt("System: <test>", "User: & more")
    assert "System: <test>" in prompt
    assert "User: & more" in prompt
    assert prompt.endswith("<|start_header_id|>assistant<|end_header_id|>\n\n")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--asyncio-mode=auto"])