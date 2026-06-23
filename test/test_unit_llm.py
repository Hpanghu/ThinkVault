"""
单元测试：LLM 模块 (core/thinkvault_llm.py) — OpenAI 兼容 API 模式
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


class TestThinkVaultLLM:
    @pytest.fixture
    def llm(self):
        from thinkvault.core.thinkvault_llm import ThinkVaultLLM
        return ThinkVaultLLM()

    def test_init_not_loaded(self, llm):
        """初始化时 is_loaded 为 False，base_url/model 正确设置"""
        assert llm.is_loaded is False
        assert llm.base_url == "http://localhost:8080/v1"
        assert llm.model == "default"

    def test_load_is_noop(self, llm):
        """load() 在 HTTP 模式下为无操作，始终返回 True"""
        result = llm.load("any_path.gguf")
        assert result is True

    def test_build_messages(self):
        from thinkvault.core.thinkvault_llm import _build_messages

        msgs = _build_messages("system prompt", [], "hello")
        assert len(msgs) == 2
        assert msgs[0] == {"role": "system", "content": "system prompt"}
        assert msgs[1] == {"role": "user", "content": "hello"}

    def test_build_messages_with_history(self):
        from thinkvault.core.thinkvault_llm import _build_messages

        history = [{"role": "user", "content": "what's 1+1"}, {"role": "assistant", "content": "2"}]
        msgs = _build_messages("sys", history, "thanks")
        assert len(msgs) == 4
        assert msgs[0] == {"role": "system", "content": "sys"}
        assert msgs[3] == {"role": "user", "content": "thanks"}

    def test_unload_is_noop(self, llm):
        """unload() 在 HTTP 模式下为无操作，不抛异常"""
        llm.unload()
        assert llm.is_loaded is False

    def test_generate_async_without_backend(self, llm):
        """无后端时 generate 抛出 LLMServiceError 而非返回错误字符串"""
        import asyncio
        from thinkvault.core.thinkvault_llm import _build_messages, LLMServiceError

        async def run():
            messages = _build_messages("system", [], "test")
            answer, stats = await llm.generate(messages, max_new_tokens=32)
            return answer, stats

        with pytest.raises(LLMServiceError) as exc_info:
            asyncio.run(run())
        assert exc_info.value.error_type == "connection_refused"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
