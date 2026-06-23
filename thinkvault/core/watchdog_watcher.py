"""
文件夹监听服务 — 基于 watchdog 库实现文件系统实时监听

当监听目录中的文件发生创建、修改、删除事件时，自动触发增量索引或清理操作。
支持防抖（2 秒合并同类事件）和文件扩展名过滤。
"""

import os
import threading
import time
from pathlib import Path

from thinkvault.core.watched_dir_store import (
    list_enabled_dirs as get_all_watched_dirs,
    add as add_watched_dir,
    update_enabled,
)
from thinkvault.core.incremental_indexer import IncrementalIndexer
from thinkvault.core.parser import DocumentParser
from thinkvault.core.scanner import _is_path_allowed
from thinkvault.utils.logger import logger

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 防抖窗口（秒）
_DEBOUNCE_SECONDS = 2

# 支持的文件扩展名集合
_SUPPORTED_TYPES = DocumentParser.SUPPORTED_TYPES


class _DebouncedHandler(FileSystemEventHandler):
    """带防抖的文件系统事件处理器

    同一路径的同类事件在 _DEBOUNCE_SECONDS 内合并，只执行最后一次。
    """

    def __init__(self, knowledge_base: str, incremental_indexer: IncrementalIndexer):
        super().__init__()
        self.knowledge_base = knowledge_base
        self.indexer = incremental_indexer
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def _is_supported_file(self, path: str) -> bool:
        """检查文件扩展名是否在支持列表中"""
        return Path(path).suffix.lower() in _SUPPORTED_TYPES

    def on_created(self, event):
        if event.is_directory or not self._is_supported_file(event.src_path):
            return
        logger.debug(f"文件创建事件: {event.src_path}")
        self._debounce(event.src_path, "created")

    def on_modified(self, event):
        if event.is_directory or not self._is_supported_file(event.src_path):
            return
        logger.debug(f"文件修改事件: {event.src_path}")
        self._debounce(event.src_path, "modified")

    def on_deleted(self, event):
        if event.is_directory or not self._is_supported_file(event.src_path):
            return
        logger.debug(f"文件删除事件: {event.src_path}")
        self._debounce(event.src_path, "deleted")

    def _debounce(self, file_path: str, event_type: str):
        """防抖：取消前一个同路径定时器，重新计时"""
        key = file_path
        with self._lock:
            # 取消已有定时器
            if key in self._timers:
                self._timers[key].cancel()
            # 新建定时器
            timer = threading.Timer(
                _DEBOUNCE_SECONDS, self._handle_event, args=(file_path, event_type)
            )
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def _handle_event(self, file_path: str, event_type: str):
        """实际处理文件事件"""
        with self._lock:
            self._timers.pop(file_path, None)

        try:
            if event_type in ("created", "modified"):
                if os.path.exists(file_path):
                    logger.info(f"监听触发索引: {file_path} ({event_type})")
                    result = self.indexer.reindex_file(file_path, self.knowledge_base)
                    if result.get("error"):
                        logger.error(f"监听索引失败: {result['error']}")
                else:
                    # 文件可能在 created/modified 后被快速删除
                    logger.info(f"监听触发清理: {file_path} (文件已不存在)")
                    self.indexer._cleanup_deleted(self.knowledge_base)
            elif event_type == "deleted":
                logger.info(f"监听触发清理: {file_path} (deleted)")
                self.indexer._cleanup_deleted(self.knowledge_base)
        except Exception as e:
            logger.error(f"处理文件事件失败: {file_path} | {e}")


class WatchdogWatcher:
    """文件夹监听服务

    基于 watchdog 库监听文件系统变更，自动触发增量索引。

    用法:
        indexer = IncrementalIndexer()
        watcher = WatchdogWatcher(watched_dir_store, indexer)
        watcher.start()   # 启动监听
        watcher.stop()    # 停止监听
    """

    def __init__(self, watched_dir_store, incremental_indexer: IncrementalIndexer):
        """初始化监听服务

        Args:
            watched_dir_store: 监听目录存储模块（thinkvault.core.watched_dir_store）
            incremental_indexer: 增量索引器实例
        """
        self._indexer = incremental_indexer
        self._observers: dict[str, Observer] = {}  # directory_path -> Observer
        self._handlers: dict[str, _DebouncedHandler] = {}  # directory_path -> Handler
        self._lock = threading.Lock()
        self._running = False

    def start(self):
        """启动监听服务

        从 watched_dir_store 读取所有 enabled=True 的记录，
        为每个监听目录启动 watchdog Observer。
        """
        if self._running:
            logger.warning("WatchdogWatcher 已在运行中，跳过重复启动")
            return

        logger.info("启动文件监听服务...")

        # 读取所有启用的监听目录
        watched_dirs = get_all_watched_dirs()
        for wd in watched_dirs:
            dir_path = wd["directory_path"]
            kb = wd["knowledge_base"]
            try:
                self._start_observer(dir_path, kb)
            except Exception as e:
                logger.error(f"启动监听失败: {dir_path} | {e}")

        self._running = True
        logger.info(f"文件监听服务已启动，共监听 {len(self._observers)} 个目录")

    def _start_observer(self, directory_path: str, knowledge_base: str):
        """为单个目录启动 Observer

        Args:
            directory_path: 监听目录路径
            knowledge_base: 对应的知识库名称
        """
        if not _is_path_allowed(directory_path):
            logger.warning(f"目录不在白名单内，跳过监听: {directory_path}")
            return

        if not os.path.isdir(directory_path):
            logger.warning(f"目录不存在，跳过监听: {directory_path}")
            return

        if directory_path in self._observers:
            logger.debug(f"目录已在监听中: {directory_path}")
            return

        handler = _DebouncedHandler(knowledge_base, self._indexer)
        observer = Observer()
        observer.schedule(handler, directory_path, recursive=True)
        observer.daemon = True
        observer.start()

        with self._lock:
            self._observers[directory_path] = observer
            self._handlers[directory_path] = handler

        logger.info(f"已启动监听: {directory_path} (KB={knowledge_base})")

    def stop(self):
        """优雅停止所有 Observer"""
        logger.info("停止文件监听服务...")

        with self._lock:
            observers_to_stop = list(self._observers.items())
            handlers_to_cleanup = list(self._handlers.values())

        for dir_path, observer in observers_to_stop:
            try:
                observer.stop()
                observer.join(timeout=5)
            except Exception as e:
                logger.error(f"停止监听失败: {dir_path} | {e}")

        # 取消所有防抖定时器
        for handler in handlers_to_cleanup:
            with handler._lock:
                for timer in handler._timers.values():
                    timer.cancel()
                handler._timers.clear()

        with self._lock:
            self._observers.clear()
            self._handlers.clear()
            self._running = False

        logger.info("文件监听服务已停止")

    def add_watch(self, directory_path: str, knowledge_base: str):
        """动态添加监听目录

        Args:
            directory_path: 监听目录路径
            knowledge_base: 对应的知识库名称
        """
        if not _is_path_allowed(directory_path):
            logger.error(
                f"目录不在白名单内: {directory_path}。"
                f"请配置 THINKVAULT_SCAN_DIRS 环境变量或将文件放到 THINKVAULT_DATA_DIR 目录下"
            )
            return

        # 持久化到 watched_dir_store
        try:
            add_watched_dir(directory_path, knowledge_base)
        except Exception as e:
            # 可能已存在，忽略唯一约束错误
            logger.debug(f"添加监听目录记录: {directory_path} | {e}")

        # 如果服务正在运行，立即启动 Observer
        if self._running:
            try:
                self._start_observer(directory_path, knowledge_base)
            except Exception as e:
                logger.error(f"启动监听失败: {directory_path} | {e}")

        logger.info(f"已添加监听: {directory_path} (KB={knowledge_base})")

    def remove_watch(self, directory_path: str):
        """动态移除监听目录

        Args:
            directory_path: 要移除的监听目录路径
        """
        with self._lock:
            observer = self._observers.pop(directory_path, None)
            handler = self._handlers.pop(directory_path, None)

        if observer:
            try:
                observer.stop()
                observer.join(timeout=5)
            except Exception as e:
                logger.error(f"停止监听失败: {directory_path} | {e}")

        if handler:
            with handler._lock:
                for timer in handler._timers.values():
                    timer.cancel()
                handler._timers.clear()

        # 禁用 watched_dir_store 中的记录
        try:
            from thinkvault.core.watched_dir_store import get_by_path
            record = get_by_path(directory_path)
            if record:
                update_enabled(record["id"], 0)
        except Exception as e:
            logger.error(f"禁用监听目录记录失败: {directory_path} | {e}")

        logger.info(f"已移除监听: {directory_path}")

    @property
    def is_running(self) -> bool:
        """监听服务是否正在运行"""
        return self._running

    @property
    def watched_directories(self) -> list[str]:
        """当前正在监听的目录列表"""
        with self._lock:
            return list(self._observers.keys())
