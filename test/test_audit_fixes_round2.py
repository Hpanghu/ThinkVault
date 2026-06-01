"""
审计修复测试（第二轮）- B17 / B18

B17: httpx.AsyncClient 跨 asyncio.run() 生命周期
B18: server lifespan 调用 unload_all → close() 清理资源
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import asyncio


# ── B17: httpx.AsyncClient 跨事件循环 ───────────────────────────

class TestB17AsyncClientLifecycle:
    """验证 HttpClient 在多次 asyncio.run() 间正确重建"""

    def test_client_recreated_after_loop_close(self):
        """第一次 asyncio.run() 创建 client → close() → 第二次应重建（非 None 且未关闭）"""
        from thinkvault.core.thinkvault_llm import ThinkVaultLLM

        llm = ThinkVaultLLM()

        async def _get_client():
            c = await llm._get_client()
            return c

        # 第一次事件循环：创建 client
        client_1 = asyncio.run(_get_client())
        assert client_1 is not None
        assert not client_1.is_closed

        # 关闭旧 client
        asyncio.run(llm.close())
        # 旧 client 应已关闭
        assert client_1.is_closed

        # 第二次事件循环：应创建新 client（非 None，未关闭）
        client_2 = asyncio.run(_get_client())
        assert client_2 is not None
        assert not client_2.is_closed

        # 清理
        asyncio.run(llm.close())

    def test_client_reused_within_same_loop(self):
        """同一事件循环内多次调用 _get_client 返回同一实例"""
        from thinkvault.core.thinkvault_llm import ThinkVaultLLM

        llm = ThinkVaultLLM()

        async def _test():
            c1 = await llm._get_client()
            c2 = await llm._get_client()
            assert id(c1) == id(c2)
            return True

        result = asyncio.run(_test())
        assert result is True

        asyncio.run(llm.close())

    def test_generate_after_loop_close_recovers(self):
        """多次 asyncio.run() 调用 generate，不应永久失败"""
        from thinkvault.core.thinkvault_llm import ThinkVaultLLM

        llm = ThinkVaultLLM()

        messages = [{"role": "user", "content": "say hi"}]

        async def _call():
            answer, stats = await llm.generate(messages, max_new_tokens=10)
            return answer, stats

        # 第一次调用（预期连接失败，但不 crash）
        answer1, stats1 = asyncio.run(_call())
        assert "[错误]" in answer1 or "error" in stats1

        # 第二次调用：先关闭 client（模拟事件循环切换）
        try:
            asyncio.run(llm.close())
        except RuntimeError:
            pass  # 事件循环已关闭时的正常行为

        # 第三次调用（应重建 client 后继续，即使仍然连不上）
        answer2, stats2 = asyncio.run(_call())
        assert "[错误]" in answer2 or "error" in stats2


# ── B18: container.unload_all 资源清理 ───────────────────────────

class TestB18ContainerCleanup:
    """验证容器关闭时正确清理资源"""

    def test_unload_all_closes_llm_client(self):
        """unload_all() 应调用 ThinkVaultLLM.close()"""
        from thinkvault.core.container import Container, _create_thinkvault_llm

        c = Container()
        c.register("thinkvault_llm", _create_thinkvault_llm)

        llm = c.get("thinkvault_llm")
        # 先创建 client
        async def _init():
            await llm._get_client()

        asyncio.run(_init())
        assert llm._client is not None
        assert not llm._client.is_closed

        # unload_all 应关闭 client
        c.unload_all()
        # 验证：client 应为 None 或已关闭
        assert llm._client is None or llm._client.is_closed

    def test_unload_all_clears_instances(self):
        """unload_all() 应清空实例字典"""
        from thinkvault.core.container import Container, _create_embedder

        c = Container()
        c.register("embedder", _create_embedder)
        emb = c.get("embedder")
        assert "embedder" in c._instances

        c.unload_all()
        assert len(c._instances) == 0

    def test_embedder_unloads_on_unload_all(self):
        """unload_all() 应调用 embedder.unload()"""
        from thinkvault.core.container import Container, _create_embedder

        c = Container()
        c.register("embedder", _create_embedder)
        emb = c.get("embedder")
        emb._model = object()  # 模拟已加载
        assert emb.is_loaded

        c.unload_all()
        assert not emb.is_loaded


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
