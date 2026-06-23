"""
共享 SQLite 连接管理 — 线程安全 + 上下文管理器 + 连接池

为 document_store 和 conversation_store 提供统一的连接管理基类，
支持单连接模式（默认）和连接池模式（高并发场景）。

连接池特性：
- 最大连接数：CPU 核心数 × 2（默认 8）
- 空闲连接超时：30 秒，超时自动关闭
- 队列管理空闲连接，获取时优先复用
- 线程安全：RLock 保护连接池操作
"""

import sqlite3
import os
import threading
import time
from pathlib import Path
from typing import Optional, List
from contextlib import contextmanager
from queue import Queue

DB_DIR = Path(os.path.expanduser("~")) / ".thinkvault"

_LOCK_TIMEOUT = 30


class SqliteConnectionPool:
    """SQLite 连接池 — 管理多个连接，支持并发访问。
    
    注意：SQLite 在 WAL 模式下支持并发读写，但写操作仍需序列化。
    连接池主要优化点：减少连接创建开销，支持同时执行多个读操作。
    """

    def __init__(self, db_path: Path, max_connections: int = 8, idle_timeout: int = 30):
        self.db_path = db_path
        self.max_connections = max_connections
        self.idle_timeout = idle_timeout
        self._pool: Queue = Queue(maxsize=max_connections)
        self._lock = threading.RLock()
        self._total_created = 0

    def _create_connection(self) -> sqlite3.Connection:
        """创建新连接（WAL 模式 + 外键开启）"""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def get(self) -> sqlite3.Connection:
        """获取连接（优先从池中获取，必要时新建）"""
        # 先尝试从空闲队列获取
        while not self._pool.empty():
            try:
                conn, created_at = self._pool.get_nowait()
                # 检查连接是否超时
                if time.time() - created_at < self.idle_timeout:
                    return conn
                # 超时则关闭
                try:
                    conn.close()
                except Exception:
                    pass
            except Exception:
                pass

        # 队列空，尝试新建连接
        with self._lock:
            if self._total_created < self.max_connections:
                conn = self._create_connection()
                self._total_created += 1
                return conn

        # 达到上限，阻塞等待
        conn, _ = self._pool.get(timeout=_LOCK_TIMEOUT)
        return conn

    def put(self, conn: sqlite3.Connection) -> None:
        """归还连接到池中"""
        try:
            self._pool.put_nowait((conn, time.time()))
        except Exception:
            # 队列满，关闭连接
            try:
                conn.close()
                with self._lock:
                    self._total_created -= 1
            except Exception:
                pass

    def close(self) -> None:
        """关闭所有连接"""
        while not self._pool.empty():
            try:
                conn, _ = self._pool.get_nowait()
                conn.close()
            except Exception:
                pass
        self._total_created = 0


class SqliteStore:
    """线程安全的 SQLite 存储基类，通过 context manager 管理连接访问。
    
    特性：
    - 实例级 RLock 序列化同一连接上的并发访问（不同 DB 文件可并行）
    - RLock 可重入，同一线程嵌套调用不会死锁
    - 锁获取超时保护，避免死锁时线程无限期挂起
    - WAL 模式支持并发读写
    - 外键强制开启
    - 可选连接池模式（高并发场景）
    
    默认使用统一的 thinkvault.db（v2.1+），可通过 db_name 参数覆盖。
    """

    def __init__(self, db_name: str = "thinkvault.db", use_pool: bool = False):
        self.db_path = DB_DIR / db_name
        self._conn: Optional[sqlite3.Connection] = None
        self._pool: Optional[SqliteConnectionPool] = None
        self._use_pool = use_pool
        self._lock = threading.RLock()

    @contextmanager
    def connect(self):
        """获取线程安全的数据库连接（上下文管理器）。

        首次调用时懒创建连接（加锁），后续复用。
        使用实例级 RLock 在 yield 期间持有锁，确保：
        - 不同线程对同一连接的访问完全序列化（无并发事务冲突）
        - 同一线程嵌套调用不会死锁（RLock 可重入）
        - 锁获取超时保护（30s），超时抛出 TimeoutError
        - 退出时无异常则自动 commit

        用法：with store.connect() as conn:  或  with store() as conn:
        """
        DB_DIR.mkdir(parents=True, exist_ok=True)

        if self._use_pool:
            # 连接池模式
            if self._pool is None:
                with self._lock:
                    if self._pool is None:
                        import os
                        max_conns = max(2, os.cpu_count() or 4) * 2
                        self._pool = SqliteConnectionPool(self.db_path, max_conns)

            acquired = self._lock.acquire(timeout=_LOCK_TIMEOUT)
            if not acquired:
                raise TimeoutError(
                    f"获取数据库锁超时（{_LOCK_TIMEOUT}s），可能存在死锁: {self.db_path}"
                )
            try:
                conn = self._pool.get()
                try:
                    yield conn
                    if conn.in_transaction:
                        try:
                            conn.commit()
                        except Exception:
                            pass
                finally:
                    self._pool.put(conn)
            finally:
                self._lock.release()
        else:
            # 单连接模式（默认）
            if self._conn is None:
                with self._lock:
                    if self._conn is None:
                        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                        self._conn.row_factory = sqlite3.Row
                        self._conn.execute("PRAGMA journal_mode=WAL")
                        self._conn.execute("PRAGMA foreign_keys=ON")

            acquired = self._lock.acquire(timeout=_LOCK_TIMEOUT)
            if not acquired:
                raise TimeoutError(
                    f"获取数据库锁超时（{_LOCK_TIMEOUT}s），可能存在死锁: {self.db_path}"
                )
            try:
                yield self._conn
                if self._conn.in_transaction:
                    try:
                        self._conn.commit()
                    except Exception:
                        pass
            finally:
                self._lock.release()

    def __call__(self):
        """支持 `with store() as conn:` 简写，等价于 `with store.connect() as conn:`。"""
        return self.connect()

    def init_schema(self, ddl: str):
        """执行 DDL 建表（通过 IF NOT EXISTS 保证幂等）。
        
        注意：executescript() 会隐式提交任何待处理事务，
        无需再显式调用 conn.commit()。
        """
        with self.connect() as conn:
            conn.executescript(ddl)

    def close(self):
        """显式关闭数据库连接。"""
        with self._lock:
            if self._use_pool:
                if self._pool is not None:
                    self._pool.close()
                    self._pool = None
            else:
                if self._conn is not None:
                    self._conn.close()
                    self._conn = None


# ── v2.1+ 统一数据库迁移 ──

def migrate_to_unified_db():
    """将旧版独立 DB 文件（documents.db, conversations.db 等）迁移到统一的 thinkvault.db。
    
    迁移策略：
    1. 检测旧 DB 文件是否存在
    2. 将每个旧 DB 的全部表复制到 thinkvault.db
    3. 复制成功后删除旧 DB 文件（可选，默认保留 .bak 后缀）
    
    此函数在应用启动时调用一次，幂等（已迁移的不会重复执行）。
    """
    import shutil
    from thinkvault.utils.logger import logger
    
    OLD_DB_FILES = [
        "documents.db",
        "conversations.db", 
        "bm25_index.db",
        "file_changes.db",
        "doc_summaries.db",
        "watched_dirs.db",
    ]
    
    unified_path = DB_DIR / "thinkvault.db"
    
    for old_name in OLD_DB_FILES:
        old_path = DB_DIR / old_name
        if not old_path.exists():
            continue
        
        try:
            # 连接旧数据库
            old_conn = sqlite3.connect(str(old_path))
            old_conn.row_factory = sqlite3.Row

            try:
                # 获取旧库中的所有表名
                tables = old_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()

                if not tables:
                    continue

                # 连接统一数据库
                DB_DIR.mkdir(parents=True, exist_ok=True)
                new_conn = sqlite3.connect(str(unified_path))
                new_conn.execute("PRAGMA journal_mode=WAL")
                new_conn.execute("PRAGMA foreign_keys=ON")

                try:
                    for (table_name,) in tables:
                        # 校验表名，防止 SQL 注入
                        if not table_name.replace("_", "").isalnum():
                            logger.warning(f"迁移跳过: 非法表名 '{table_name}'")
                            continue

                        # 检查统一库中是否已有此表
                        exists = new_conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                            (table_name,)
                        ).fetchone()

                        if exists:
                            # 表已存在，检查是否为空（空表则从旧库迁移）
                            count = new_conn.execute(f"SELECT COUNT(*) FROM [{table_name}]").fetchone()[0]
                            if count > 0:
                                logger.info(f"迁移跳过: {table_name} 已存在于 thinkvault.db（{count} 行）")
                                continue

                        # 复制表结构和数据
                        rows = old_conn.execute(f"SELECT * FROM [{table_name}]").fetchall()
                        if not rows:
                            continue

                        columns = [desc[0] for desc in old_conn.execute(f"PRAGMA table_info([{table_name}])").fetchall()]
                        placeholders = ",".join(["?" for _ in columns])
                        cols_str = ",".join(columns)

                        # 创建表（如果不存在）
                        create_sql = old_conn.execute(
                            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                            (table_name,)
                        ).fetchone()[0]
                        new_conn.execute(create_sql)

                        # 批量插入
                        new_conn.executemany(
                            f"INSERT OR IGNORE INTO [{table_name}] ({cols_str}) VALUES ({placeholders})",
                            [tuple(row) for row in rows]
                        )
                        new_conn.commit()
                        logger.info(f"迁移完成: {old_name}::{table_name} → thinkvault.db（{len(rows)} 行）")
                finally:
                    new_conn.close()
            finally:
                old_conn.close()
            
            # 备份旧文件
            bak_path = old_path.with_suffix(".db.bak")
            shutil.move(str(old_path), str(bak_path))
            logger.info(f"旧数据库已备份: {old_name} → {old_name}.bak")
            
        except Exception as e:
            logger.warning(f"数据库迁移失败 [{old_name}]: {e}")