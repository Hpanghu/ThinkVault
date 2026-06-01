"""
单元测试：数据库基类 (core/db.py)
"""

import sys
import sqlite3
import threading
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
        # 第二次执行不应报错
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
            conn.commit()
        with store.connect() as conn:
            row = conn.execute("SELECT val FROM items WHERE id=1").fetchone()
            assert row["val"] == "hello"

    def test_close(self, store):
        with store.connect() as conn:
            conn.execute("SELECT 1")
        store.close()
        assert store._conn is None

    def test_thread_safety(self, store):
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
                    conn.commit()
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

        with store.connect() as conn:
            count = conn.execute("SELECT COUNT(*) as cnt FROM t_safe").fetchone()
            assert count["cnt"] == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
