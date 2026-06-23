"""
单元测试：数据库基类 (core/db.py)

测试策略：分段式压力梯度
  L1: 单线程读写（基线）
  L2: 2 线程并发（轻量）
  L3: 10 线程并发（标准）
  L4: 50 线程并发（压力）
  + 嵌套调用无死锁验证
  + 超时保护验证
"""

import sys
import sqlite3
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from thinkvault.core.db import SqliteStore

TEST_DB = "test_unit_db.db"


@pytest.fixture
def store():
    s = SqliteStore(TEST_DB)
    yield s
    s.close()
    # 清理
    db_path = Path.home() / ".thinkvault" / TEST_DB
    if db_path.exists():
        db_path.unlink()


class TestSqliteStore:
    def test_connect_returns_connection(self, store):
        with store.connect() as conn:
            assert isinstance(conn, sqlite3.Connection)

    def test_wal_mode(self, store):
        with store.connect() as conn:
            row = conn.execute("PRAGMA journal_mode").fetchone()
            assert row[0].lower() == "wal"

    def test_foreign_keys_on(self, store):
        with store.connect() as conn:
            row = conn.execute("PRAGMA foreign_keys").fetchone()
            assert row[0] == 1

    def test_init_schema_idempotent(self, store):
        ddl = "CREATE TABLE IF NOT EXISTS test_t (id INTEGER PRIMARY KEY, name TEXT)"
        store.init_schema(ddl)
        store.init_schema(ddl)
        with store.connect() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='test_t'"
            ).fetchone()
            assert row is not None

    def test_write_and_read(self, store):
        store.init_schema(
            "CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, val TEXT)"
        )
        with store.connect() as conn:
            conn.execute("INSERT INTO items (id, val) VALUES (1, 'hello')")
            # contextmanager 退出时自动 commit
        with store.connect() as conn:
            row = conn.execute("SELECT val FROM items WHERE id=1").fetchone()
            assert row["val"] == "hello"

    def test_close(self, store):
        with store.connect() as conn:
            conn.execute("SELECT 1")
        store.close()
        assert store._conn is None

    def test_nested_connect_no_deadlock(self, store):
        """嵌套调用 connect() 不会死锁（RLock 可重入）"""
        store.init_schema(
            "CREATE TABLE IF NOT EXISTS t_nested (id INTEGER PRIMARY KEY, val TEXT)"
        )
        with store.connect() as conn1:
            conn1.execute("INSERT INTO t_nested (id, val) VALUES (1, 'outer')")
            with store.connect() as conn2:
                assert conn2 is conn1  # 同一连接
                conn2.execute("INSERT INTO t_nested (id, val) VALUES (2, 'inner')")
        with store.connect() as conn:
            count = conn.execute("SELECT COUNT(*) as cnt FROM t_nested").fetchone()
            assert count["cnt"] == 2

    # ── 分段式压力测试 ──────────────────────────────────────────

    @pytest.mark.parametrize("n_threads", [1, 2, 10, 50], ids=["L1", "L2", "L3", "L4"])
    def test_thread_safety(self, store, n_threads):
        """分段式线程安全测试：1/2/10/50 线程并发写入"""
        store.init_schema(
            "CREATE TABLE IF NOT EXISTS t_safe (id INTEGER PRIMARY KEY, val TEXT)"
        )
        errors = []

        def writer(n):
            try:
                with store.connect() as conn:
                    conn.execute(
                        "INSERT INTO t_safe (id, val) VALUES (?, ?)", (n, str(n))
                    )
            except Exception as e:
                errors.append(str(e))

        start = time.time()
        threads = [threading.Thread(target=writer, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)  # 超时保护：60s 内必须完成

        elapsed = time.time() - start
        hung = [t for t in threads if t.is_alive()]

        # 断言：无死锁
        assert len(hung) == 0, f"{len(hung)} 线程超时挂起（可能死锁），耗时 {elapsed:.1f}s"
        # 断言：无错误
        assert len(errors) == 0, f"线程错误: {errors}"
        # 断言：数据完整
        with store.connect() as conn:
            count = conn.execute("SELECT COUNT(*) as cnt FROM t_safe").fetchone()
            assert count["cnt"] == n_threads


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
