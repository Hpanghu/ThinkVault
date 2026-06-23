"""
BM25 索引持久化存储 — 将序列化的 BM25 索引缓存到磁盘

避免每次冷启动时从 ChromaDB 全量加载并重建 BM25 索引。
20 万文件（~2M chunks）场景下，冷启动重建需 18-53s，
从磁盘加载约 1-3s。

存储方式：
- 元数据（chunk_id 列表、知识库信息）存 SQLite
- 序列化的 BM25 索引存 gzip 压缩的 JSON 文件
- 同目录下与 SQLite 同级的 bm25_indexes/ 子目录

失效策略：
- 知识库 chunk 数量变化时自动失效（对比 stored_chunk_count 与当前值）
- 通过 delete_index() / delete_all() 主动清理
"""

import gzip
import json
import os
import time
from pathlib import Path
from typing import Optional

from thinkvault.core.base_store import BaseStore
from thinkvault.core.db import SqliteStore
from thinkvault.utils.logger import logger

BM25_INDEX_SCHEMA = """
    CREATE TABLE IF NOT EXISTS bm25_index_meta (
        knowledge_base TEXT PRIMARY KEY,
        chunk_count INTEGER NOT NULL,
        doc_count INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        file_path TEXT NOT NULL,
        compressed INTEGER NOT NULL DEFAULT 1
    )
"""

_MIGRATIONS: list[str] = [
    "ALTER TABLE bm25_index_meta ADD COLUMN compressed INTEGER NOT NULL DEFAULT 1",
]

_index_dir: Optional[Path] = None


class _Store(BaseStore):
    _SCHEMA = BM25_INDEX_SCHEMA
    _MIGRATIONS = _MIGRATIONS

    def _get_store(self) -> SqliteStore:
        store = super()._get_store()
        _ensure_index_dir()
        return store


_instance = _Store()


def _get_index_dir() -> Path:
    """获取 BM25 索引文件存储目录"""
    global _index_dir
    if _index_dir is None:
        from thinkvault.core.db import DB_DIR
        _index_dir = DB_DIR / "bm25_indexes"
    return _index_dir


def _ensure_index_dir():
    """确保索引文件目录存在"""
    _get_index_dir().mkdir(parents=True, exist_ok=True)


def save_index(
    knowledge_base: str,
    doc_ids: list[str],
    doc_texts: list[str],
    doc_metadatas: list[dict],
    bm25_corpus: list[list[str]],
    bm25_params: dict,
) -> bool:
    """将 BM25 索引持久化到磁盘（gzip 压缩）

    Args:
        knowledge_base: 知识库名称
        doc_ids: 文档 ID 列表
        doc_texts: 文档文本列表
        doc_metadatas: 文档元数据列表
        bm25_corpus: BM25 分词后的语料库（list of token lists）
        bm25_params: BM25 模型参数（doc_len, avgdl, k1, b, epsilon 等）

    Returns:
        是否保存成功
    """
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    _ensure_index_dir()
    # 优先使用 .json.gz 压缩格式，兼容旧 .json 格式
    index_file_gz = _get_index_dir() / f"{knowledge_base}.json.gz"
    index_file_plain = _get_index_dir() / f"{knowledge_base}.json"

    try:
        # 序列化索引数据
        index_data = {
            "version": 2,
            "knowledge_base": knowledge_base,
            "doc_ids": doc_ids,
            "doc_texts": doc_texts,
            "doc_metadatas": doc_metadatas,
            "bm25_corpus": bm25_corpus,
            "bm25_params": bm25_params,
            "created_at": now,
        }

        # 写入 gzip 压缩文件（原子性：先写临时文件再重命名）
        tmp_file = index_file_gz.with_suffix(".json.gz.tmp")
        with gzip.open(tmp_file, "wt", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False)
        if index_file_gz.exists():
            index_file_gz.unlink()
        tmp_file.rename(index_file_gz)

        # 清理旧版未压缩文件
        if index_file_plain.exists():
            index_file_plain.unlink()

        # 更新元数据到 SQLite
        compressed_size = index_file_gz.stat().st_size
        with _instance._get_store().connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO bm25_index_meta
                   (knowledge_base, chunk_count, doc_count, created_at, updated_at, file_path, compressed)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    knowledge_base,
                    len(doc_ids),
                    len(set(m.get("source_file", "") for m in doc_metadatas)),
                    now,
                    now,
                    str(index_file_gz),
                    1,
                ),
            )
            conn.commit()

        logger.info(
            f"BM25 索引已持久化 (gzip): 知识库 [{knowledge_base}], "
            f"{len(doc_ids)} chunks, 压缩后 {compressed_size / 1024:.0f}KB"
        )
        return True

    except Exception as e:
        logger.error(f"BM25 索引持久化失败 [{knowledge_base}]: {e}")
        return False


def load_index(knowledge_base: str, expected_chunk_count: int = -1) -> Optional[dict]:
    """从磁盘加载 BM25 索引（自动检测 gzip/明文格式）

    Args:
        knowledge_base: 知识库名称
        expected_chunk_count: 期望的 chunk 数量，不匹配时返回 None（-1 表示不检查）

    Returns:
        索引数据字典，包含 doc_ids, doc_texts, doc_metadatas, bm25_corpus, bm25_params
        加载失败或 chunk 数不匹配时返回 None
    """
    index_dir = _get_index_dir()
    index_file_gz = index_dir / f"{knowledge_base}.json.gz"
    index_file_plain = index_dir / f"{knowledge_base}.json"

    # 优先加载 gzip 压缩格式，回退到明文格式
    index_data = None
    if index_file_gz.exists():
        try:
            with gzip.open(index_file_gz, "rt", encoding="utf-8") as f:
                index_data = json.load(f)
        except Exception as e:
            logger.warning(f"BM25 gzip 索引加载失败 [{knowledge_base}]: {e}")
    elif index_file_plain.exists():
        try:
            with open(index_file_plain, "r", encoding="utf-8") as f:
                index_data = json.load(f)
        except Exception as e:
            logger.warning(f"BM25 索引加载失败 [{knowledge_base}]: {e}")

    if index_data is None:
        return None

    # 版本检查（v1 和 v2 均兼容）
    version = index_data.get("version", 1)
    if version not in (1, 2):
        logger.warning(f"BM25 索引版本不兼容 [{knowledge_base}]: {version}")
        return None

    # chunk 数量检查
    stored_count = len(index_data.get("doc_ids", []))
    if expected_chunk_count >= 0 and stored_count != expected_chunk_count:
        logger.info(
            f"BM25 索引 chunk 数不匹配 [{knowledge_base}]: "
            f"缓存 {stored_count}, 当前 {expected_chunk_count}，需重建"
        )
        return None

    logger.info(
        f"BM25 索引从磁盘加载: 知识库 [{knowledge_base}], {stored_count} chunks"
        f"{' (gzip)' if index_file_gz.exists() else ''}"
    )
    return index_data


def delete_index(knowledge_base: str) -> bool:
    """删除指定知识库的 BM25 索引缓存"""
    index_dir = _get_index_dir()
    deleted = False

    try:
        for ext in [".json.gz", ".json"]:
            index_file = index_dir / f"{knowledge_base}{ext}"
            if index_file.exists():
                index_file.unlink()
                deleted = True

        # 删除元数据
        with _instance._get_store().connect() as conn:
            conn.execute(
                "DELETE FROM bm25_index_meta WHERE knowledge_base=?",
                (knowledge_base,),
            )
            conn.commit()

        if deleted:
            logger.info(f"已删除 BM25 索引缓存: [{knowledge_base}]")
        return True

    except Exception as e:
        logger.error(f"删除 BM25 索引缓存失败 [{knowledge_base}]: {e}")
        return False


def delete_all() -> int:
    """删除所有 BM25 索引缓存

    Returns:
        删除的索引数量
    """
    count = 0
    index_dir = _get_index_dir()

    try:
        for pattern in ["*.json.gz", "*.json"]:
            for f in index_dir.glob(pattern):
                f.unlink()
                count += 1

        with _instance._get_store().connect() as conn:
            cursor = conn.execute("DELETE FROM bm25_index_meta")
            conn.commit()
            count = max(count, cursor.rowcount)

        logger.info(f"已删除所有 BM25 索引缓存: {count} 个")
        return count

    except Exception as e:
        logger.error(f"删除所有 BM25 索引缓存失败: {e}")
        return count


def get_index_meta(knowledge_base: str) -> Optional[dict]:
    """获取指定知识库的 BM25 索引元数据"""
    with _instance._get_store().connect() as conn:
        row = conn.execute(
            "SELECT * FROM bm25_index_meta WHERE knowledge_base=?",
            (knowledge_base,),
        ).fetchone()

    if row is None:
        return None
    return dict(row)


def list_indexes() -> list[dict]:
    """列出所有已持久化的 BM25 索引"""
    with _instance._get_store().connect() as conn:
        rows = conn.execute(
            "SELECT * FROM bm25_index_meta ORDER BY updated_at DESC"
        ).fetchall()

    return [dict(r) for r in rows]
