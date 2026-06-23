"""
向量存储 — ChromaDB 嵌入式向量数据库

HNSW 参数调优说明：
- ef_construct：构建时搜索宽度，越大索引质量越高但构建越慢（默认 200）
- M：每层最大连接数，越大召回率越高但内存占用越大（默认 16）
- ef_search：查询时搜索宽度，越大召回率越高但查询越慢

可通过环境变量配置：
- THINKVAULT_HNSW_EF_CONSTRUCT：构建参数（默认 200）
- THINKVAULT_HNSW_M：连接数参数（默认 32，平衡召回率和内存）
- THINKVAULT_HNSW_EF_SEARCH：查询参数（默认 100，平衡速度和召回率）
"""

import os
import threading
from pathlib import Path
from typing import Optional

from thinkvault.utils.logger import logger

DEFAULT_DB_DIR = Path(os.path.expanduser("~")) / ".thinkvault" / "chromadb"

# HNSW 参数（可通过环境变量覆盖）
_HNSW_EF_CONSTRUCT = int(os.environ.get("THINKVAULT_HNSW_EF_CONSTRUCT", "200"))
_HNSW_M = int(os.environ.get("THINKVAULT_HNSW_M", "32"))
_HNSW_EF_SEARCH = int(os.environ.get("THINKVAULT_HNSW_EF_SEARCH", "100"))


class VectorStore:
    """管理知识库的向量存储，每个知识库对应一个 ChromaDB collection"""

    def __init__(self, db_dir: str = None):
        self.db_dir = str(db_dir or DEFAULT_DB_DIR)
        self._client = None
        self._lock = threading.Lock()

    def _get_client(self):
        if self._client is None:
            with self._lock:
                if self._client is None:
                    try:
                        import chromadb
                        Path(self.db_dir).mkdir(parents=True, exist_ok=True)
                        self._client = chromadb.PersistentClient(path=self.db_dir)
                    except Exception as e:
                        logger.error(f"chromadb 不可用: {e}")
                        logger.error("向量存储已降级，检索功能将返回空结果")
                        self._client = False  # 标记为不可用
        if self._client is False:
            return None
        return self._client

    def _safe_name(self, knowledge_base: str) -> str:
        """将知识库名转为安全的 collection 名称。
        
        编码规则：空格 → _，原始 _ → __（双下划线），短横线保留。
        解码（list_knowledge_bases）：__ → _，_ → 空格。
        """
        return knowledge_base.replace("_", "__").replace(" ", "_")

    def _restore_name(self, safe_name: str) -> str:
        """从 collection 名称还原知识库名（_safe_name 的逆操作）"""
        name = safe_name
        result = []
        i = 0
        while i < len(name):
            if name[i] == '_' and i + 1 < len(name) and name[i + 1] == '_':
                result.append('_')
                i += 2
            elif name[i] == '_':
                result.append(' ')
                i += 1
            else:
                result.append(name[i])
                i += 1
        return ''.join(result)

    def get_or_create_collection(self, knowledge_base: str = "default"):
        """获取或创建知识库 collection（使用优化后的 HNSW 参数）"""
        client = self._get_client()
        if client is None:
            raise RuntimeError("chromadb 不可用，向量存储已降级")
        safe_name = self._safe_name(knowledge_base)
        full_name = f"kb_{safe_name}"

        # 尝试获取已有 collection
        try:
            return client.get_collection(name=full_name)
        except Exception:
            pass

        # 创建新 collection，使用优化后的 HNSW 参数
        metadata = {
            "hnsw:space": "cosine",
            "hnsw:construction_ef": _HNSW_EF_CONSTRUCT,
            "hnsw:M": _HNSW_M,
            "hnsw:search_ef": _HNSW_EF_SEARCH,
        }

        logger.info(
            f"创建向量集合 [{full_name}]: "
            f"ef_construct={_HNSW_EF_CONSTRUCT}, M={_HNSW_M}, ef_search={_HNSW_EF_SEARCH}"
        )
        return client.create_collection(name=full_name, metadata=metadata)

    def add_chunks(self, knowledge_base: str, chunks, embeddings: list[list[float]]):
        """批量添加文档块到向量库"""
        collection = self.get_or_create_collection(knowledge_base)

        ids = []
        documents = []
        metadatas = []
        for chunk in chunks:
            chunk_id = f"{chunk.source_file}_{chunk.chunk_index}"
            ids.append(chunk_id)
            documents.append(chunk.text)
            metadatas.append({
                "source_file": chunk.source_file,
                "source_page": chunk.source_page,
                "chunk_index": chunk.chunk_index,
                **chunk.metadata,
            })

        # 如果 ID 已存在，先删除
        existing = collection.get(ids=ids)
        if existing["ids"]:
            collection.delete(ids=existing["ids"])

        collection.add(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

        logger.info(f"已索引 {len(chunks)} 个文档块到知识库 [{knowledge_base}]")
        return len(chunks)

    def search(self, knowledge_base: str, query_embedding: list[float], top_k: int = 5) -> list[dict]:
        """向量相似度检索（支持查询时 ef_search 动态调整）

        ChromaDB 的 HNSW 索引支持查询时调整 ef_search 参数，
        较高的 ef_search 提升召回率但增加延迟。
        可通过 THINKVAULT_HNSW_EF_SEARCH 环境变量控制。
        """
        try:
            collection = self.get_or_create_collection(knowledge_base)
        except RuntimeError:
            return []  # chromadb 不可用，返回空结果

        # 动态调整查询时 ef_search
        # ChromaDB 1.x 支持 modify() 修改 search_ef
        if _HNSW_EF_SEARCH != 100:  # 非默认值时尝试更新
            try:
                collection.modify(metadata={"hnsw:search_ef": _HNSW_EF_SEARCH})
            except Exception:
                pass  # 旧版 ChromaDB 不支持 modify，忽略

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        hits = []
        if results["ids"] and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                hits.append({
                    "id": results["ids"][0][i],
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else 0,
                })
        return hits

    def delete_knowledge_base(self, knowledge_base: str):
        """删除知识库"""
        client = self._get_client()
        if client is None:
            logger.warning("chromadb 不可用，跳过知识库删除")
            return
        safe_name = f"kb_{self._safe_name(knowledge_base)}"
        try:
            client.delete_collection(name=safe_name)
            logger.info(f"知识库 [{knowledge_base}] 已删除")
        except Exception as e:
            logger.warning(f"删除知识库失败: {e}")

    def list_knowledge_bases(self) -> list[str]:
        """列出所有知识库"""
        client = self._get_client()
        if client is None:
            return []  # chromadb 不可用
        collections = client.list_collections()
        result = []
        for c in collections:
            if c.name.startswith("kb_"):
                safe_name = c.name[3:]
                result.append(self._restore_name(safe_name))
            else:
                result.append(c.name)
        return result

    def get_chunk_count(self, knowledge_base: str = "default") -> int:
        """获取知识库文档块数量"""
        try:
            collection = self.get_or_create_collection(knowledge_base)
            return collection.count()
        except Exception:
            return 0

    def rebuild_collection(self, knowledge_base: str) -> bool:
        """重建知识库集合（使用优化后的 HNSW 参数）

        将旧集合的数据迁移到新集合，应用最新的 HNSW 配置。
        适用于从旧版升级或调整 HNSW 参数后需要重建索引的场景。
        """
        client = self._get_client()
        if client is None:
            logger.warning("chromadb 不可用，跳过集合重建")
            return False

        safe_name = self._safe_name(knowledge_base)
        full_name = f"kb_{safe_name}"

        try:
            old_collection = client.get_collection(name=full_name)
        except Exception:
            logger.info(f"集合 [{full_name}] 不存在，无需重建")
            return True

        # 全量读取旧集合数据
        chunk_count = old_collection.count()
        if chunk_count == 0:
            logger.info(f"集合 [{full_name}] 为空，无需重建")
            return True

        logger.info(f"开始重建集合 [{full_name}]: {chunk_count} chunks")
        _READ_BATCH = 5000
        all_ids, all_docs, all_metas, all_embs = [], [], [], []
        offset = 0

        while offset < chunk_count:
            batch = old_collection.get(
                include=["documents", "metadatas", "embeddings"],
                limit=_READ_BATCH,
                offset=offset,
            )
            all_ids.extend(batch["ids"])
            all_docs.extend(batch["documents"])
            all_metas.extend(batch.get("metadatas", [{}] * len(batch["ids"])))
            if batch.get("embeddings"):
                all_embs.extend(batch["embeddings"])
            offset += len(batch["ids"])

        # 删除旧集合
        client.delete_collection(name=full_name)

        # 创建新集合（使用优化后的 HNSW 参数）
        metadata = {
            "hnsw:space": "cosine",
            "hnsw:construction_ef": _HNSW_EF_CONSTRUCT,
            "hnsw:M": _HNSW_M,
            "hnsw:search_ef": _HNSW_EF_SEARCH,
        }
        new_collection = client.create_collection(name=full_name, metadata=metadata)

        # 分批写入数据，降低内存峰值
        _WRITE_BATCH = 500
        total = len(all_ids)
        has_embeddings = bool(all_embs)
        for i in range(0, total, _WRITE_BATCH):
            end = min(i + _WRITE_BATCH, total)
            batch_kwargs = dict(
                ids=all_ids[i:end],
                documents=all_docs[i:end],
                metadatas=all_metas[i:end],
            )
            if has_embeddings:
                batch_kwargs["embeddings"] = all_embs[i:end]
            new_collection.add(**batch_kwargs)
            logger.debug(
                f"集合重建 [{full_name}]: 写入批次 {i // _WRITE_BATCH + 1}/{(total + _WRITE_BATCH - 1) // _WRITE_BATCH}"
            )

        # 释放内存
        del all_ids, all_docs, all_metas, all_embs

        logger.info(
            f"集合重建完成 [{full_name}]: {total} chunks, "
            f"分 {(total + _WRITE_BATCH - 1) // _WRITE_BATCH} 批写入, "
            f"HNSW M={_HNSW_M}, ef_construct={_HNSW_EF_CONSTRUCT}, ef_search={_HNSW_EF_SEARCH}"
        )
        return True


# 全局单例已移除 — 请通过 container.get("vector_store") 或 container.vector_store 获取实例
