"""
向量存储 — ChromaDB 嵌入式向量数据库
"""

import os
import threading
from pathlib import Path
from typing import Optional

from thinkvault.utils.logger import logger

DEFAULT_DB_DIR = Path(os.path.expanduser("~")) / ".thinkvault" / "chromadb"


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
                    except ImportError:
                        logger.error("chromadb 未安装")
                        raise
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
        """获取或创建知识库 collection"""
        client = self._get_client()
        safe_name = self._safe_name(knowledge_base)
        return client.get_or_create_collection(name=f"kb_{safe_name}")

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
        """向量相似度检索"""
        collection = self.get_or_create_collection(knowledge_base)

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
        safe_name = f"kb_{self._safe_name(knowledge_base)}"
        try:
            client.delete_collection(name=safe_name)
            logger.info(f"知识库 [{knowledge_base}] 已删除")
        except Exception as e:
            logger.warning(f"删除知识库失败: {e}")

    def list_knowledge_bases(self) -> list[str]:
        """列出所有知识库"""
        client = self._get_client()
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


# 全局单例已移除 — 请通过 container.get("vector_store") 或 container.vector_store 获取实例
