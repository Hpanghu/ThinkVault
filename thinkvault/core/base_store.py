"""Store 模块基类，统一惰性初始化、线程安全和迁移管理"""
import threading
from thinkvault.core.db import SqliteStore
from thinkvault.utils.logger import logger


class BaseStore:
    """Store 模块基类

    子类需设置:
        _SCHEMA: str — CREATE TABLE 语句
        _MIGRATIONS: list[str] — ALTER TABLE 迁移语句列表
        _DB_NAME: str — 数据库文件名 (默认 "thinkvault.db")
    """
    _SCHEMA: str = ""
    _MIGRATIONS: list[str] = []
    _DB_NAME: str = "thinkvault.db"

    def __init__(self):
        self._store: SqliteStore | None = None
        self._lock = threading.Lock()

    def _get_store(self) -> SqliteStore:
        if self._store is not None:
            return self._store
        with self._lock:
            if self._store is not None:
                return self._store
            store = SqliteStore(db_name=self._DB_NAME, use_pool=True)
            store.init_schema(self._SCHEMA)
            self._run_migrations(store)
            self._store = store
            return self._store

    def _run_migrations(self, store: SqliteStore):
        import sqlite3
        for sql in self._MIGRATIONS:
            try:
                with store.connect() as conn:
                    conn.execute(sql)
                    conn.commit()
            except sqlite3.OperationalError as e:
                # 列/表已存在属于正常情况（幂等迁移），仅 debug 记录
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    logger.debug(f"迁移跳过 (已应用): {sql[:60]}...")
                else:
                    logger.warning(f"数据库迁移失败: {sql[:60]}... | 错误: {e}")
            except Exception as e:
                logger.warning(f"数据库迁移异常: {sql[:60]}... | 错误: {e}")

    def close(self):
        if self._store is not None:
            self._store.close()
            self._store = None
