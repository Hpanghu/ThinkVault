"""
增量索引引擎 — 基于 content_hash + mtime 检测文件变更，实现增量索引

与 scanner.py 的全量扫描不同，IncrementalIndexer 只处理新增、修改、删除的文件，
跳过内容未变更的文件，大幅减少重复索引的开销。
"""

import hashlib
import os
from pathlib import Path

from thinkvault.core import file_change_store
from thinkvault.core import document_store as doc_store
from thinkvault.core.container import container
from thinkvault.core.indexer import index_document
from thinkvault.core.parser import DocumentParser
from thinkvault.core.scanner import _is_path_allowed
from thinkvault.utils.logger import logger

# 分块读取的块大小（64 KB）
_HASH_BUF_SIZE = 65536


class IncrementalIndexer:
    """增量索引器：基于内容哈希检测文件变更，只索引有变化的文件"""

    @staticmethod
    def compute_hash(file_path: str) -> str:
        """计算文件的 SHA-256 哈希值，分块读取避免大文件内存爆炸

        Args:
            file_path: 文件绝对路径

        Returns:
            str: 十六进制格式的 SHA-256 哈希值
        """
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                buf = f.read(_HASH_BUF_SIZE)
                if not buf:
                    break
                sha256.update(buf)
        return sha256.hexdigest()

    def scan(
        self,
        directory_path: str,
        knowledge_base: str = "default",
        recursive: bool = True,
    ) -> dict:
        """扫描目录，检测文件变更并增量索引

        扫描流程：
        1. 遍历目录中所有支持的文件
        2. 对每个文件计算 content_hash，获取 file_size、mtime
        3. 对比 file_change_store 中的记录判断变更类型
        4. 对新增/修改的文件执行索引，清理已删除文件

        Args:
            directory_path: 要扫描的目录路径
            knowledge_base: 目标知识库名称
            recursive: 是否递归扫描子目录

        Returns:
            dict: 扫描结果统计
        """
        result = {
            "scanned": 0,
            "new": 0,
            "updated": 0,
            "deleted": 0,
            "skipped": 0,
            "errors": [],
        }

        # 路径安全检查
        if not _is_path_allowed(directory_path):
            result["errors"].append(
                f"目录不在允许扫描的白名单内: {directory_path}。"
                f"请配置 THINKVAULT_SCAN_DIRS 环境变量或将文件放到 THINKVAULT_DATA_DIR 目录下"
            )
            return result

        dir_path = Path(directory_path)
        if not dir_path.exists():
            result["errors"].append(f"目录不存在: {directory_path}")
            return result

        if not dir_path.is_dir():
            result["errors"].append(f"路径不是目录: {directory_path}")
            return result

        # 收集磁盘上的文件
        pattern = "**/*" if recursive else "*"
        disk_files = {}
        for f in dir_path.glob(pattern):
            if f.is_file() and f.suffix.lower() in DocumentParser.SUPPORTED_TYPES:
                disk_files[str(f)] = f

        result["scanned"] = len(disk_files)

        # 查询该 KB 下已有的变更记录
        existing_records = file_change_store.get_by_knowledge_base(knowledge_base)
        existing_map = {r["file_path"]: r for r in existing_records}

        # ---- 处理磁盘上的文件 ----
        pending_files = []  # (file_path, is_update, content_hash)

        for file_path_str, file_path_obj in disk_files.items():
            try:
                content_hash = self.compute_hash(file_path_str)
                stat = file_path_obj.stat()
                file_size = stat.st_size
                mtime = stat.st_mtime

                record = existing_map.get(file_path_str)

                if record is None:
                    # 新文件：file_change_store 无记录
                    file_change_store.upsert(
                        file_path=file_path_str,
                        file_name=file_path_obj.name,
                        knowledge_base=knowledge_base,
                        file_size=file_size,
                        mtime=mtime,
                        content_hash=content_hash,
                        status="pending",
                    )
                    pending_files.append((file_path_str, False, content_hash))
                elif record["content_hash"] != content_hash or record["mtime"] != mtime:
                    # 已修改：content_hash 不同或 mtime 变化
                    self._delete_old_index(record)
                    file_change_store.upsert(
                        file_path=file_path_str,
                        file_name=file_path_obj.name,
                        knowledge_base=knowledge_base,
                        file_size=file_size,
                        mtime=mtime,
                        content_hash=content_hash,
                        status="pending",
                    )
                    pending_files.append((file_path_str, True, content_hash))
                else:
                    # 未修改：跳过
                    result["skipped"] += 1
                    logger.debug(f"跳过未变更文件: {file_path_str}")

            except Exception as e:
                result["errors"].append(f"{file_path_str}: {e}")
                logger.error(f"扫描文件失败: {file_path_str} | {e}")

        # ---- 处理已删除的文件 ----
        for file_path_str, record in existing_map.items():
            if file_path_str not in disk_files:
                try:
                    self._delete_old_index(record)
                    file_change_store.update_status(file_path_str, "deleted")
                    result["deleted"] += 1
                    logger.info(f"标记已删除文件: {file_path_str}")
                except Exception as e:
                    result["errors"].append(f"{file_path_str}: 删除索引失败 - {e}")
                    logger.error(f"删除索引失败: {file_path_str} | {e}")

        # ---- 索引待处理文件 ----
        for file_path_str, is_update, content_hash in pending_files:
            try:
                index_result = self._index_file(file_path_str, knowledge_base, content_hash=content_hash)
                if index_result.get("error"):
                    result["errors"].append(index_result["error"])
                elif is_update:
                    result["updated"] += 1
                else:
                    result["new"] += 1
            except Exception as e:
                result["errors"].append(f"{file_path_str}: {e}")
                logger.error(f"索引文件失败: {file_path_str} | {e}")

        logger.info(
            f"增量扫描完成: {directory_path} | "
            f"扫描={result['scanned']} 新增={result['new']} "
            f"更新={result['updated']} 删除={result['deleted']} "
            f"跳过={result['skipped']} 错误={len(result['errors'])}"
        )
        return result

    def _index_file(self, file_path: str, knowledge_base: str, content_hash: str = None) -> dict:
        """索引单个文件：解析 → 分块 → 向量化 → 存储

        Args:
            file_path: 文件绝对路径
            knowledge_base: 目标知识库名称
            content_hash: 预计算的文件内容哈希，传入则避免重复计算

        Returns:
            dict: 索引结果，包含 doc_id、chunk_count 或 error
        """
        path = Path(file_path)
        result = {"file_path": file_path}

        idx_result = index_document(file_path, knowledge_base)

        if idx_result["status"] != "success":
            error_msg = idx_result.get("error") or "索引失败"
            file_change_store.update_status(
                file_path, "error", error_message=error_msg
            )
            result["error"] = f"{path.name}: {error_msg}"
            return result

        # 获取文件信息
        stat = path.stat()
        if content_hash is None:
            content_hash = self.compute_hash(file_path)

        # 更新变更记录
        file_change_store.upsert(
            file_path=file_path,
            file_name=path.name,
            knowledge_base=knowledge_base,
            file_size=stat.st_size,
            mtime=stat.st_mtime,
            content_hash=content_hash,
            status="pending",
        )
        file_change_store.update_status(
            file_path, "indexed", chunk_count=idx_result["chunks_count"], doc_id=idx_result["document_id"]
        )

        result["doc_id"] = idx_result["document_id"]
        result["chunk_count"] = idx_result["chunks_count"]
        logger.info(f"索引成功: {path.name} ({idx_result['chunks_count']} 块, KB={knowledge_base})")
        return result

    def _delete_old_index(self, record: dict):
        """删除旧索引数据

        如果变更记录中有关联的 doc_id，则删除 document_store 和 vector_store 中的对应数据。

        Args:
            record: file_change_store 中的记录
        """
        doc_id = record.get("doc_id")
        if doc_id:
            # 删除 vector_store 中的 chunks
            try:
                kb = record.get("knowledge_base", "default")
                collection = container.vector_store.get_or_create_collection(kb)
                # 按文件名匹配删除旧 chunks
                file_name = record.get("file_name", "")
                if file_name:
                    old_chunks = collection.get(
                        where={"source_file": file_name}
                    )
                    if old_chunks and old_chunks["ids"]:
                        collection.delete(ids=old_chunks["ids"])
            except Exception as e:
                logger.warning(f"删除旧向量数据失败: {record.get('file_path')} | {e}")

            # 删除 document_store 记录
            try:
                doc_store.delete_document(doc_id)
            except Exception as e:
                logger.warning(f"删除旧文档记录失败: {doc_id} | {e}")

    def _cleanup_deleted(self, knowledge_base: str) -> int:
        """清理已删除文件的索引

        查询该 KB 下所有变更记录，检查文件是否仍然存在。
        如果文件不存在，清理其索引数据。

        Args:
            knowledge_base: 知识库名称

        Returns:
            int: 清理的记录数
        """
        cleaned = 0
        records = file_change_store.get_by_knowledge_base(knowledge_base)

        for record in records:
            file_path = record["file_path"]
            if not os.path.exists(file_path):
                try:
                    self._delete_old_index(record)
                    file_change_store.delete(file_path)
                    cleaned += 1
                    logger.info(f"清理已删除文件索引: {file_path}")
                except Exception as e:
                    logger.error(f"清理失败: {file_path} | {e}")

        return cleaned

    def reindex_file(self, file_path: str, knowledge_base: str = "default") -> dict:
        """强制重新索引指定文件

        无论 content_hash 是否变化，都重新解析、分块、向量化并存储。
        如果该文件有旧索引，先删除旧索引再重新索引。

        Args:
            file_path: 文件绝对路径
            knowledge_base: 目标知识库名称

        Returns:
            dict: 索引结果
        """
        # 检查旧记录并删除旧索引
        old_record = file_change_store.get_by_path(file_path)
        if old_record:
            self._delete_old_index(old_record)

        # 执行索引
        result = self._index_file(file_path, knowledge_base)

        return result
