"""
共享 SQLite 连接管理 — 线程安全 + 上下文管理器

为 document_store 和 conversation_store 提供统一的连接管理基类，
消除约 40 行重复代码。每个操作通过 context manager 获取连接并序列化写入。
"""

import sqlite3
import os
import threading
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

DB_DIR = Path(os.path.expanduser("~")) / ".thinkvault"


class SqliteStore:
    """线程安全的 SQLite 存储基类，通过 context manager 管理连接访问。
    
    特性：
    - 双检锁 + 模块级单例连接复用
    - WAL 模式支持并发读写
    - 外键强制开启
    - 所有写操作经锁序列化
    """

    def __init__(self, db_name: str):
        self.db_path = DB_DIR / db_name
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

    @contextmanager
    def connect(self):
        """上下文管理器 — 返回线程安全的数据库连接。
        
        首次调用时懒创建连接，后续复用。上下文退出前持有锁，
        确保调用者完成 commit 后才释放。
        """
        DB_DIR.mkdir(parents=True, exist_ok=True)
        if self._conn is None:
            with self._lock:
                if self._conn is None:
                    self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                    self._conn.row_factory = sqlite3.Row
                    self._conn.execute("PRAGMA journal_mode=WAL")
                    self._conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            yield self._conn

    def init_schema(self, ddl: str):
        """执行 DDL 建表（通过 IF NOT EXISTS 保证幂等）。"""
        with self.connect() as conn:
            conn.executescript(ddl)
            conn.commit()

    def close(self):
        """显式关闭数据库连接。"""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
