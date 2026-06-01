"""
依赖注入容器 — 管理所有核心服务单例

将全局单例改为容器统一管理，支持：
- 延迟初始化（惰性加载）
- 显式生命周期控制
- 替换/注入测试替身
"""

import threading
from typing import Optional


class Container:
    """轻量级 IOC 容器，管理 ThinkVault 核心服务实例"""

    def __init__(self):
        self._lock = threading.Lock()
        self._instances: dict = {}
        self._factories: dict = {}

    def register(self, name: str, factory, lazy: bool = True):
        """注册服务工厂函数。lazy=True 表示首次 get 时才创建实例。"""
        self._factories[name] = factory
        if not lazy:
            self._instances[name] = factory()

    def get(self, name: str):
        """获取服务实例（惰性创建）"""
        if name in self._instances:
            return self._instances[name]

        factory = self._factories.get(name)
        if factory is None:
            raise KeyError(f"未注册的服务: {name}")

        with self._lock:
            # 双重检查
            if name not in self._instances:
                self._instances[name] = factory()
        return self._instances[name]

    def set(self, name: str, instance):
        """显式设置实例（用于测试替身注入）"""
        self._instances[name] = instance

    def reset(self, name: str = None):
        """重置指定服务（或全部服务），释放资源后重新惰性初始化"""
        if name is None:
            self._instances.clear()
        elif name in self._instances:
            del self._instances[name]

    def unload_all(self):
        """卸载所有服务实例（用于应用关闭）"""
        # embedder
        if "embedder" in self._instances:
            try:
                self._instances["embedder"].unload()
            except Exception:
                pass
        # thinkvault_llm — 关闭 httpx 连接池
        if "thinkvault_llm" in self._instances:
            import asyncio
            try:
                llm = self._instances["thinkvault_llm"]
                # 尝试异步关闭 httpx client；若当前无运行中的事件循环则跳过
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(llm.close())
                except RuntimeError:
                    # 无运行事件循环（如同步测试环境），尝试新建临时循环
                    try:
                        asyncio.run(llm.close())
                    except Exception:
                        pass
            except Exception:
                pass
        self._instances.clear()

    # ---- 便捷属性 ----

    @property
    def embedder(self):
        return self.get("embedder")

    @property
    def vector_store(self):
        return self.get("vector_store")

    @property
    def retriever(self):
        return self.get("retriever")

    @property
    def thinkvault_llm(self):
        return self.get("thinkvault_llm")


# ---- 工厂函数 ----

def _create_embedder():
    from thinkvault.core.embedder import Embedder
    return Embedder()


def _create_vector_store():
    from thinkvault.core.storage import VectorStore
    return VectorStore()


def _create_retriever():
    from thinkvault.core.retriever import Retriever
    return Retriever()


def _create_thinkvault_llm():
    import os
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM
    url = os.environ.get("THINKVAULT_LLM_URL", "http://localhost:11434/v1")
    model = os.environ.get("THINKVAULT_LLM_MODEL", "llama3.2:1b")
    api_key = os.environ.get("THINKVAULT_LLM_API_KEY", None)
    return ThinkVaultLLM(base_url=url, model=model, api_key=api_key)


# ---- 全局容器 ----

container = Container()

# 注册所有核心服务（惰性加载）
container.register("embedder", _create_embedder)
container.register("vector_store", _create_vector_store)
container.register("retriever", _create_retriever)
container.register("thinkvault_llm", _create_thinkvault_llm)