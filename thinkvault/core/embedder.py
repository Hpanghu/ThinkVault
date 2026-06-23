"""
向量化引擎 — Embedding 模型管理 + 文本向量化

支持三种推理后端（按优先级自动选择）：
1. ONNX Runtime（最快，CPU 推理速度提升 2-5 倍）
2. sentence-transformers（PyTorch，兼容性最好）
3. 外部 API 模式（Ollama / OpenAI / 自建服务）

ONNX Runtime 加速原理：
- 将 PyTorch 模型导出为 ONNX 格式，使用 onnxruntime 推理
- 支持 CPU 优化（AVX2/AVX512）、量化（INT8/FP16）
- 首次使用自动导出 ONNX 模型并缓存到磁盘
"""

import os
import threading
from pathlib import Path
from typing import Optional, Any

from thinkvault.utils.logger import logger
from thinkvault.utils.security import validate_url_for_ssrf


class Embedder:
    """文本向量化，支持 ONNX Runtime / PyTorch / 外部 API 三种模式"""

    DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"

    def __init__(self, model_name: Optional[str] = None, cache_dir: Optional[str] = None):
        self.model_name = model_name or self.DEFAULT_MODEL
        self.cache_dir = cache_dir
        self._model: Any = None
        self._onnx_session: Any = None
        self._onnx_tokenizer: Any = None
        self._load_lock = threading.Lock()

        # ONNX Runtime 配置
        self._use_onnx = os.environ.get("THINKVAULT_USE_ONNX", "1").lower() in ("1", "true")
        self._onnx_quantized = os.environ.get("THINKVAULT_ONNX_QUANTIZED", "0").lower() in ("1", "true")

        # 外部 API 模式配置（SSRF 防护）
        api_url = os.environ.get("THINKVAULT_EMBEDDING_API_URL", "")
        try:
            if api_url:
                safe_url = validate_url_for_ssrf(api_url)
                self._api_url = safe_url
            else:
                self._api_url = ""
        except ValueError as e:
            logger.warning(f"SSRF 防护拒绝 embedding API URL: {api_url}，禁用 API 模式")
            self._api_url = ""
        self._api_key = os.environ.get("THINKVAULT_EMBEDDING_API_KEY", "")
        self._api_model = os.environ.get("THINKVAULT_EMBEDDING_API_MODEL", "")
        self._api_dimension = int(os.environ.get("THINKVAULT_EMBEDDING_DIMENSION", "512"))
        self._api_client: Any = None

    @property
    def is_loaded(self) -> bool:
        if self._api_url:
            return True  # API 模式无需加载模型
        return self._model is not None or self._onnx_session is not None

    @property
    def is_api_mode(self) -> bool:
        return bool(self._api_url)

    @property
    def is_onnx_mode(self) -> bool:
        return self._onnx_session is not None

    def load(self) -> bool:
        """加载模型（优先 ONNX Runtime，回退 PyTorch，API 模式始终返回 True）"""
        if self._api_url:
            logger.info(f"Embedding 使用外部 API: {self._api_url}")
            return True

        if self._model is not None or self._onnx_session is not None:
            return True

        with self._load_lock:
            if self._model is not None or self._onnx_session is not None:
                return True

            # 尝试 ONNX Runtime 加速
            if self._use_onnx:
                if self._load_onnx():
                    return True
                logger.info("ONNX Runtime 加载失败，回退到 PyTorch 推理")

            # 回退到 sentence-transformers
            return self._load_pytorch()

    def _get_model_cache_dir(self) -> str:
        """获取模型缓存目录"""
        if self.cache_dir is not None:
            return self.cache_dir

        _env_dir = os.environ.get("THINKVAULT_MODEL_DIR", "")
        if _env_dir and Path(_env_dir).is_dir():
            self.cache_dir = _env_dir
        else:
            try:
                import appdirs
                self.cache_dir = appdirs.user_cache_dir("thinkvault", "thinkvault")
            except ImportError:
                self.cache_dir = str(Path(__file__).parent.parent.parent / "test" / "models")
        return self.cache_dir

    def _resolve_model_path(self) -> str:
        """解析模型路径（支持 HuggingFace 缓存格式）"""
        model_path = self.model_name
        if "/" in self.model_name:
            cache_dir = self._get_model_cache_dir()
            safe_name = "models--" + self.model_name.replace("/", "--")
            cache_repo = os.path.join(cache_dir, safe_name)
            if os.path.isdir(cache_repo):
                snapshots_dir = os.path.join(cache_repo, "snapshots")
                if os.path.isdir(snapshots_dir):
                    revisions = sorted(os.listdir(snapshots_dir))
                    if revisions:
                        local_path = os.path.join(snapshots_dir, revisions[-1])
                        if os.path.isfile(os.path.join(local_path, "model.safetensors")):
                            model_path = local_path
                            logger.info(f"使用本地缓存: {local_path}")
        return model_path

    def _load_onnx(self) -> bool:
        """加载 ONNX Runtime 推理会话

        流程：
        1. 检查磁盘上是否有已导出的 ONNX 模型
        2. 有 → 直接加载
        3. 无 → 先加载 PyTorch 模型，导出 ONNX，再加载
        """
        try:
            import onnxruntime as ort
        except ImportError:
            logger.debug("onnxruntime 未安装，跳过 ONNX 加速")
            return False

        try:
            from sentence_transformers import SentenceTransformer
            import numpy as np

            # 确定 ONNX 模型缓存路径
            onnx_dir = Path(self._get_model_cache_dir()) / "onnx"
            onnx_dir.mkdir(parents=True, exist_ok=True)

            model_tag = self.model_name.replace("/", "--")
            if self._onnx_quantized:
                onnx_file = onnx_dir / f"{model_tag}_quantized.onnx"
            else:
                onnx_file = onnx_dir / f"{model_tag}.onnx"

            # 如果 ONNX 模型不存在，从 PyTorch 导出
            if not onnx_file.exists():
                logger.info(f"导出 ONNX 模型到: {onnx_file}")
                model_path = self._resolve_model_path()
                st_model = SentenceTransformer(model_path)

                # 导出为 ONNX
                dummy_input = {"input_ids": np.zeros((1, 10), dtype=np.int64),
                               "attention_mask": np.ones((1, 10), dtype=np.int64)}
                if "token_type_ids" in st_model.tokenize(["test"]):
                    dummy_input["token_type_ids"] = np.zeros((1, 10), dtype=np.int64)

                onnx_file_str = str(onnx_file)
                st_model.save(str(onnx_dir / f"{model_tag}_tmp"), safe_serialization=True)

                # 使用 sentence-transformers 内置的 ONNX 导出
                try:
                    from sentence_transformers.onnx import OnnxBackend
                    st_model.to_onnx(str(onnx_file))
                except (ImportError, Exception):
                    # 手动导出
                    import torch
                    import onnx
                    device = next(st_model.parameters()).device
                    st_model.eval()

                    encoding = st_model.tokenize(["test"])
                    input_ids = encoding["input_ids"].to(device)
                    attention_mask = encoding["attention_mask"].to(device)

                    torch.onnx.export(
                        st_model[0].auto_model,
                        (input_ids, attention_mask),
                        onnx_file_str,
                        input_names=["input_ids", "attention_mask"],
                        output_names=["last_hidden_state", "pooler_output"],
                        dynamic_axes={
                            "input_ids": {0: "batch", 1: "seq"},
                            "attention_mask": {0: "batch", 1: "seq"},
                            "last_hidden_state": {0: "batch", 1: "seq"},
                        },
                        opset_version=14,
                    )

                logger.info(f"ONNX 模型已导出: {onnx_file}")

            # 加载 ONNX Runtime 会话
            sess_options = ort.SessionOptions()
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            sess_options.intra_op_num_threads = 0  # 使用所有 CPU 核心
            sess_options.inter_op_num_threads = 0

            # 自动检测可用的执行提供者（GPU 优先）
            providers = self._detect_onnx_providers(ort)

            self._onnx_session = ort.InferenceSession(
                str(onnx_file), sess_options=sess_options, providers=providers
            )

            # 加载 tokenizer（仍需要 sentence-transformers 的 tokenizer）
            model_path = self._resolve_model_path()
            from transformers import AutoTokenizer
            self._onnx_tokenizer = AutoTokenizer.from_pretrained(model_path)

            logger.info(
                f"ONNX Runtime 加载成功: {self.model_name}, "
                f"providers={self._onnx_session.get_providers()}"
            )
            return True

        except Exception as e:
            logger.debug(f"ONNX Runtime 加载失败: {e}")
            self._onnx_session = None
            self._onnx_tokenizer = None
            return False

    def _load_pytorch(self) -> bool:
        """加载 sentence-transformers PyTorch 模型（支持 FP16 加速）"""
        try:
            from sentence_transformers import SentenceTransformer

            model_path = self._resolve_model_path()
            self._model = SentenceTransformer(model_path)

            # FP16 半精度推理（CPU 上无加速，仅 GPU 有效）
            use_fp16 = os.environ.get("THINKVAULT_FP16", "0").lower() in ("1", "true")
            if use_fp16:
                try:
                    import torch
                    if torch.cuda.is_available():
                        self._model = self._model.half().to("cuda")
                        logger.info(f"Embedding 模型加载成功 (PyTorch FP16/CUDA): {self.model_name}")
                    else:
                        logger.info("FP16 需 CUDA GPU，回退到 FP32 CPU 推理")
                        logger.info(f"Embedding 模型加载成功 (PyTorch): {self.model_name}")
                except Exception as e:
                    logger.debug(f"FP16 加速失败: {e}")
                    logger.info(f"Embedding 模型加载成功 (PyTorch): {self.model_name}")
            else:
                logger.info(f"Embedding 模型加载成功 (PyTorch): {self.model_name}")
            return True
        except ImportError as e:
            logger.error(f"sentence-transformers 导入失败: {e}")
            logger.error(
                "请安装: pip install sentence-transformers torch\n"
                "或设置 THINKVAULT_EMBEDDING_API_URL 使用外部 Embedding API"
            )
            return False
        except Exception as e:
            logger.error(f"Embedding 模型加载失败: {e}")
            return False

    @staticmethod
    def _detect_onnx_providers(ort) -> list[str | tuple[str, dict[str, object]]]:
        """自动检测可用的 ONNX Runtime 执行提供者

        检测优先级：CUDA → DirectML → CPU
        - CUDA: NVIDIA GPU，需 onnxruntime-gpu + CUDA Toolkit
        - DirectML: Windows 任意 GPU（AMD/Intel/NVIDIA），需 onnxruntime-directml
        - CPU: 始终可用
        """
        available = ort.get_available_providers()
        providers: list[str | tuple[str, dict[str, object]]] = []

        # CUDA（NVIDIA GPU，性能最佳）
        if "CUDAExecutionProvider" in available:
            try:
                # 验证 CUDA 是否真正可用
                providers.append(("CUDAExecutionProvider", {
                    "device_id": 0,
                    "arena_extend_strategy": "kNextPowerOfTwo",
                    "gpu_mem_limit": 2 * 1024 * 1024 * 1024,  # 2GB 上限
                    "cudnn_conv_algo_search": "EXHAUSTIVE",
                }))
                logger.info("ONNX Runtime: 检测到 CUDA GPU 加速")
            except Exception:
                pass

        # DirectML（Windows 任意 GPU，兼容性最佳）
        if "DmlExecutionProvider" in available and not providers:
            try:
                providers.append(("DmlExecutionProvider", {
                    "device_id": 0,
                }))
                logger.info("ONNX Runtime: 检测到 DirectML GPU 加速")
            except Exception:
                pass

        # CPU 始终作为后备
        providers.append("CPUExecutionProvider")

        if not any(p == "CPUExecutionProvider" or (isinstance(p, tuple) and p[0] != "CUDAExecutionProvider" and p[0] != "DmlExecutionProvider") for p in providers[:1]):
            logger.info(f"ONNX Runtime: 使用 CPU 推理")

        return providers

    def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """批量文本向量化"""
        if not self.is_loaded:
            if not self.load():
                return None

        # API 模式
        if self._api_url:
            return self._embed_via_api(texts)

        # ONNX Runtime 模式
        if self._onnx_session is not None:
            return self._embed_via_onnx(texts)

        # PyTorch 模式
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

    def _embed_via_onnx(self, texts: list[str]) -> Optional[list[list[float]]]:
        """使用 ONNX Runtime 进行推理"""
        try:
            import numpy as np

            # Tokenize
            encoded = self._onnx_tokenizer(
                texts, padding=True, truncation=True,
                max_length=512, return_tensors="np"
            )

            # ONNX 推理
            input_feed = {
                "input_ids": encoded["input_ids"].astype(np.int64),
                "attention_mask": encoded["attention_mask"].astype(np.int64),
            }
            if "token_type_ids" in encoded:
                input_feed["token_type_ids"] = encoded["token_type_ids"].astype(np.int64)

            outputs = self._onnx_session.run(None, input_feed)

            # Mean pooling + normalize（与 sentence-transformers 一致）
            last_hidden = outputs[0]  # (batch, seq, dim)
            attention_mask = encoded["attention_mask"].astype(np.float32)
            mask_expanded = np.expand_dims(attention_mask, -1)
            sum_embeddings = np.sum(last_hidden * mask_expanded, axis=1)
            sum_mask = np.clip(np.sum(attention_mask, axis=1, keepdims=True), a_min=1e-9, a_max=None)
            mean_embeddings = sum_embeddings / sum_mask

            # L2 normalize
            norms = np.linalg.norm(mean_embeddings, axis=1, keepdims=True)
            normalized = mean_embeddings / np.clip(norms, a_min=1e-9, a_max=None)

            return normalized.tolist()

        except Exception as e:
            logger.warning(f"ONNX 推理失败，回退到 PyTorch: {e}")
            # 回退到 PyTorch
            if self._model is None:
                self._load_pytorch()
            if self._model is not None:
                embeddings = self._model.encode(
                    texts, normalize_embeddings=True, show_progress_bar=False
                )
                return embeddings.tolist()
            return None

    def embed_single(self, text: str) -> Optional[list[float]]:
        result = self.embed([text])
        return result[0] if result else None

    def _embed_via_api(self, texts: list[str]) -> Optional[list[list[float]]]:
        """通过外部 API 进行文本向量化（OpenAI 兼容接口）"""
        try:
            import httpx

            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"

            # OpenAI 兼容的 /v1/embeddings 接口
            payload = {
                "input": texts,
                "model": self._api_model or self.model_name,
            }

            url = self._api_url.rstrip("/")
            if not url.endswith("/embeddings"):
                url = f"{url}/embeddings"

            # 复用持久化 httpx 客户端
            if self._api_client is None:
                self._api_client = httpx.Client(timeout=30.0)
            resp = self._api_client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            # 解析 OpenAI 格式响应
            embeddings = []
            for item in sorted(data.get("data", []), key=lambda x: x.get("index", 0)):
                embeddings.append(item["embedding"])

            if len(embeddings) != len(texts):
                logger.error(f"API 返回嵌入数量不匹配: 请求 {len(texts)}, 返回 {len(embeddings)}")
                return None

            return embeddings

        except ImportError:
            logger.error("API 模式需要 httpx，请安装: pip install httpx")
            return None
        except Exception as e:
            logger.error(f"Embedding API 调用失败: {e}")
            return None

    def unload(self):
        if self._model is not None:
            del self._model
            self._model = None
        if self._onnx_session is not None:
            del self._onnx_session
            self._onnx_session = None
        self._onnx_tokenizer = None
        if self._api_client is not None:
            self._api_client.close()
            self._api_client = None


# 全局单例已移除 — 请通过 container.get("embedder") 或 container.embedder 获取实例
