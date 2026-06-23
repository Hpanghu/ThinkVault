"""
后台任务队列 — 轻量级异步任务管理器

将文件索引、摘要生成等耗时操作移至后台执行，
避免阻塞 API 请求，用户可继续使用其他功能。
"""

import asyncio
import uuid
from typing import Any, Callable, Optional
from thinkvault.utils.logger import logger


class BackgroundTask:
    """单个后台任务"""

    def __init__(self, task_id: str, task_type: str, description: str):
        self.task_id = task_id
        self.task_type = task_type  # "scan" | "summary" | "reindex"
        self.description = description
        self.status: str = "pending"  # pending | running | completed | failed
        self.progress: float = 0.0
        self.result: Any = None
        self.error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "description": self.description,
            "status": self.status,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
        }


class BackgroundTaskManager:
    """后台任务管理器 — 基于 asyncio.Queue 的轻量级实现"""

    def __init__(self, max_concurrent: int = 2):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._tasks: dict[str, BackgroundTask] = {}
        self._workers: list[asyncio.Task] = []
        self._max_concurrent = max_concurrent
        self._running = False

    def start(self):
        """启动工作协程"""
        if self._running:
            return
        self._running = True
        for i in range(self._max_concurrent):
            worker = asyncio.create_task(self._worker(i))
            self._workers.append(worker)
        logger.info(f"后台任务管理器已启动，{self._max_concurrent} 个工作协程")

    async def stop(self):
        """停止工作协程"""
        self._running = False
        # 放入哨兵值让 worker 退出
        for _ in self._workers:
            await self._queue.put(None)
        for worker in self._workers:
            try:
                await asyncio.wait_for(worker, timeout=5.0)
            except asyncio.TimeoutError:
                worker.cancel()
        self._workers.clear()
        logger.info("后台任务管理器已停止")

    def submit(
        self,
        task_type: str,
        description: str,
        func: Callable,
        *args,
        **kwargs,
    ) -> str:
        """提交后台任务，返回 task_id"""
        task_id = str(uuid.uuid4())[:8]
        task = BackgroundTask(task_id, task_type, description)
        self._tasks[task_id] = task
        self._queue.put_nowait((task, func, args, kwargs))
        logger.info(f"后台任务已提交: [{task_id}] {description}")
        return task_id

    def get_task(self, task_id: str) -> Optional[BackgroundTask]:
        return self._tasks.get(task_id)

    def list_tasks(self, task_type: str = None) -> list[dict]:
        tasks = self._tasks.values()
        if task_type:
            tasks = [t for t in tasks if t.task_type == task_type]
        return [t.to_dict() for t in tasks]

    async def _worker(self, worker_id: int):
        """工作协程：从队列取任务执行"""
        while self._running:
            try:
                item = await self._queue.get()
                if item is None:
                    break
                task, func, args, kwargs = item
                task.status = "running"
                logger.info(f"Worker-{worker_id} 开始执行: [{task.task_id}] {task.description}")
                try:
                    # 同步函数用 to_thread，异步函数直接 await
                    if asyncio.iscoroutinefunction(func):
                        result = await func(*args, **kwargs)
                    else:
                        result = await asyncio.to_thread(func, *args, **kwargs)
                    task.status = "completed"
                    task.progress = 1.0
                    task.result = result
                    logger.info(f"Worker-{worker_id} 完成: [{task.task_id}] {task.description}")
                except Exception as e:
                    task.status = "failed"
                    task.error = str(e)
                    logger.error(f"Worker-{worker_id} 失败: [{task.task_id}] {e}")
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker-{worker_id} 异常: {e}")


# 全局单例
task_manager = BackgroundTaskManager()
