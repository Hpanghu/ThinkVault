"""
硬件检测工具 — 自动检测 GPU/VRAM/RAM，辅助模型推荐
"""

import psutil
from dataclasses import dataclass, field


@dataclass
class HardwareProfile:
    os_name: str = ""
    cpu_count: int = 0
    cpu_name: str = ""
    total_ram_gb: float = 0.0
    available_ram_gb: float = 0.0
    gpu_name: str = ""
    vram_gb: float = 0.0
    has_cuda: bool = False
    gpu_backend: str = ""
    has_mps: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def recommended_model_tier(self) -> str:
        """根据硬件返回推荐模型档位：'light' / 'medium' / 'high' / 'ultra'"""
        if self.vram_gb >= 16 or self.total_ram_gb >= 32:
            return "ultra"
        if self.vram_gb >= 8 or self.total_ram_gb >= 16:
            return "high"
        if self.vram_gb >= 4 or self.total_ram_gb >= 8:
            return "medium"
        return "light"

    @property
    def recommended_model_spec(self) -> dict:
        """返回推荐模型规格"""
        tiers = {
            "light":  {"params": "1.5B~3B", "quant": "Q4_K_M", "vram_needed": "2GB", "description": "轻量模型，8GB 内存可流畅运行"},
            "medium": {"params": "7B",       "quant": "Q4_K_M", "vram_needed": "5GB", "description": "平衡性能与速度"},
            "high":   {"params": "14B",      "quant": "Q4_K_M", "vram_needed": "9GB", "description": "高质量回答，需 8GB+ 显存"},
            "ultra":  {"params": "20B~32B",  "quant": "Q4_K_M", "vram_needed": "13GB+", "description": "旗舰体验，需 16GB+ 显存"},
        }
        return tiers[self.recommended_model_tier]


def detect_hardware() -> HardwareProfile:
    """检测当前机器硬件配置"""
    profile = HardwareProfile()
    import platform
    profile.os_name = platform.system()
    profile.cpu_count = psutil.cpu_count(logical=True) or 0
    profile.cpu_name = platform.processor()
    mem = psutil.virtual_memory()
    profile.total_ram_gb = round(mem.total / (1024 ** 3), 1)
    profile.available_ram_gb = round(mem.available / (1024 ** 3), 1)

    try:
        import torch
        # NVIDIA CUDA
        profile.has_cuda = torch.cuda.is_available()
        if profile.has_cuda:
            profile.gpu_name = torch.cuda.get_device_name(0)
            vram_bytes = torch.cuda.get_device_properties(0).total_memory
            profile.vram_gb = round(vram_bytes / (1024 ** 3), 1)
            profile.gpu_backend = "CUDA"
        # Apple Silicon MPS
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            profile.has_mps = True
            profile.gpu_name = "Apple Silicon (MPS)"
            # MPS 共享系统内存，用可用内存的 60% 估算 VRAM
            profile.vram_gb = round(profile.available_ram_gb * 0.6, 1)
            profile.gpu_backend = "MPS"
        else:
            profile.gpu_backend = "CPU"
    except ImportError:
        profile.warnings.append("未安装 torch，无法检测 GPU 加速环境")

    return profile


def recommend_model_tier(profile: HardwareProfile) -> str:
    """独立函数：根据硬件配置返回推荐模型档位"""
    return profile.recommended_model_tier


MODEL_TIER_RECOMMENDATIONS = {
    "light": {
        "models": [
            {"name": "qwen2.5-0.5b-instruct-q4_k_m.gguf", "url": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf", "size": "~0.4GB"},
            {"name": "qwen2.5-1.5b-instruct-q4_k_m.gguf", "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf", "size": "~1.0GB"},
        ],
    },
    "medium": {
        "models": [
            {"name": "qwen2.5-3b-instruct-q4_k_m.gguf", "url": "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf", "size": "~2.0GB"},
            {"name": "qwen2.5-7b-instruct-q4_k_m.gguf", "url": "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m.gguf", "size": "~4.7GB"},
        ],
    },
    "high": {
        "models": [
            {"name": "qwen2.5-14b-instruct-q4_k_m.gguf", "url": "https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF/resolve/main/qwen2.5-14b-instruct-q4_k_m.gguf", "size": "~9GB"},
            {"name": "qwen2.5-7b-instruct-q8_0.gguf", "url": "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q8_0.gguf", "size": "~8GB"},
        ],
    },
    "ultra": {
        "models": [
            {"name": "qwen2.5-32b-instruct-q4_k_m.gguf", "url": "https://huggingface.co/Qwen/Qwen2.5-32B-Instruct-GGUF/resolve/main/qwen2.5-32b-instruct-q4_k_m.gguf", "size": "~20GB"},
        ],
    },
}
