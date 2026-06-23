"""
依赖注入容器 — 管理所有核心服务单例

将全局单例改为容器统一管理，支持：
- 延迟初始化（惰性加载）
- 显式生命周期控制
- 替换/注入测试替身
"""

import threading
from typing import Optional

from thinkvault.utils.logger import logger


class Container:
    """轻量级 IOC 容器，管理 ThinkVault 核心服务实例"""

    def __init__(self):
        self._lock = threading.RLock()
        self._instances: dict = {}
        self._factories: dict = {}

    def register(self, name: str, factory, lazy: bool = True):
        """注册服务工厂函数。lazy=True 表示首次 get 时才创建实例。"""
        with self._lock:
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
                logger.debug("卸载 embedder 失败", exc_info=True)
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
                        logger.debug("同步关闭 LLM 客户端失败", exc_info=True)
            except Exception:
                logger.debug("卸载 thinkvault_llm 失败", exc_info=True)
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

    @property
    def incremental_indexer(self):
        return self.get("incremental_indexer")

    @property
    def summary_generator(self):
        return self.get("summary_generator")

    @property
    def watchdog_watcher(self):
        return self.get("watchdog_watcher")

    @property
    def file_change_store(self):
        return self.get("file_change_store")

    @property
    def doc_summary_store(self):
        return self.get("doc_summary_store")

    @property
    def watched_dir_store(self):
        return self.get("watched_dir_store")

    @property
    def bm25_index_store(self):
        return self.get("bm25_index_store")


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
    url = os.environ.get("THINKVAULT_LLM_URL", "http://localhost:8080/v1")
    model = os.environ.get("THINKVAULT_LLM_MODEL", "default")
    api_key = os.environ.get("THINKVAULT_LLM_API_KEY", None)
    return ThinkVaultLLM(base_url=url, model=model, api_key=api_key)


def _create_incremental_indexer():
    from thinkvault.core.incremental_indexer import IncrementalIndexer
    return IncrementalIndexer()


def _create_summary_generator():
    from thinkvault.core.summary_generator import SummaryGenerator
    return SummaryGenerator()


def _create_watchdog_watcher():
    from thinkvault.core import watched_dir_store as _watched_dir_store
    from thinkvault.core.watchdog_watcher import WatchdogWatcher
    # 复用容器中的 incremental_indexer 单例，确保索引状态一致
    return WatchdogWatcher(_watched_dir_store, container.incremental_indexer)


# ── Store 模块访问器（委托给模块级单例，保持 IOC 容器一致性）──

class _ModuleAccessor:
    """将模块级函数调用包装为对象方法，使 IOC 容器可统一管理。
    
    每个 Store 模块（file_change_store, doc_summary_store 等）
    使用模块级单例 + 惰性 _get_store() 模式，其公开函数作为模块级函数暴露。
    此访问器通过 __getattr__ 将方法调用委托给底层模块，
    同时作为容器中的一等实例，支持 set() 注入测试替身。
    """
    def __init__(self, module):
        self._module = module
    
    def __getattr__(self, name):
        # 委托给底层模块的函数
        return getattr(self._module, name)


def _get_file_change_store():
    from thinkvault.core import file_change_store as _module
    return _ModuleAccessor(_module)


def _get_doc_summary_store():
    from thinkvault.core import doc_summary_store as _module
    return _ModuleAccessor(_module)


def _get_watched_dir_store():
    from thinkvault.core import watched_dir_store as _module
    return _ModuleAccessor(_module)


def _get_bm25_index_store():
    from thinkvault.core import bm25_index_store as _module
    return _ModuleAccessor(_module)


# ---- 全局容器 ----

container = Container()

# 注册所有核心服务（惰性加载）
container.register("embedder", _create_embedder)
container.register("vector_store", _create_vector_store)
container.register("retriever", _create_retriever)
container.register("thinkvault_llm", _create_thinkvault_llm)
container.register("incremental_indexer", _create_incremental_indexer)
container.register("summary_generator", _create_summary_generator)
container.register("watchdog_watcher", _create_watchdog_watcher)
container.register("file_change_store", _get_file_change_store)
container.register("doc_summary_store", _get_doc_summary_store)
container.register("watched_dir_store", _get_watched_dir_store)
container.register("bm25_index_store", _get_bm25_index_store)