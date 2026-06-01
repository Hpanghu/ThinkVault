"""
向量化引擎 — Embedding 模型管理 + 文本向量化
"""

import os
import threading
from typing import Optional

from thinkvault.utils.logger import logger


class Embedder:
    """文本向量化，默认使用 bge-small-zh"""

    DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"

    def __init__(self, model_name: str = None, cache_dir: str = None):
        self.model_name = model_name or self.DEFAULT_MODEL
        self.cache_dir = cache_dir
        self._model = None
        self._load_lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> bool:
        if self._model is not None:
            return True
        with self._load_lock:
            if self._model is not None:
                return True
            try:
                from sentence_transformers import SentenceTransformer

                # 延迟设置默认缓存路径（优先环境变量，兜底 appdirs）
                if self.cache_dir is None:
                    import pathlib as _pl
                    _env_dir = os.environ.get("THINKVAULT_MODEL_DIR", "")
                    if _env_dir and _pl.Path(_env_dir).is_dir():
                        self.cache_dir = _env_dir
                    else:
                        # 使用标准用户缓存目录，兼容 pip install 部署
                        try:
                            import appdirs
                            self.cache_dir = appdirs.user_cache_dir("thinkvault", "thinkvault")
                        except ImportError:
                            _project_root = _pl.Path(__file__).parent.parent.parent
                            self.cache_dir = str(_project_root / "test" / "models")

                # 如果是 HuggingFace 模型名，尝试从本地缓存加载
                model_path = self.model_name
                if "/" in self.model_name and self.cache_dir:
                    # 转换为本地缓存路径: org/model → models--org--model/snapshots/<hash>
                    safe_name = "models--" + self.model_name.replace("/", "--")
                    cache_repo = os.path.join(self.cache_dir, safe_name)
                    if os.path.isdir(cache_repo):
                        # 查找 snapshots 下的最新 revision
                        snapshots_dir = os.path.join(cache_repo, "snapshots")
                        if os.path.isdir(snapshots_dir):
                            revisions = sorted(os.listdir(snapshots_dir))
                            if revisions:
                                local_path = os.path.join(snapshots_dir, revisions[-1])
                                if os.path.isfile(os.path.join(local_path, "model.safetensors")):
                                    model_path = local_path
                                    logger.info(f"使用本地缓存: {local_path}")

                self._model = SentenceTransformer(model_path)
                logger.info(f"Embedding 模型加载成功: {self.model_name}")
                return True
            except ImportError:
                logger.error("sentence-transformers 未安装")
                return False
            except Exception as e:
                logger.error(f"Embedding 模型加载失败: {e}")
                return False

    def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """批量文本向量化"""
        if not self.is_loaded:
            if not self.load():
                return None

        try:
            embeddings = self._model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"向量化失败: {e}")
            return None

    def embed_single(self, text: str) -> Optional[list[float]]:
        result = self.embed([text])
        return result[0] if result else None

    def unload(self):
        if self._model is not None:
            del self._model
            self._model = None


# 全局单例已移除 — 请通过 container.get("embedder") 或 container.embedder 获取实例
