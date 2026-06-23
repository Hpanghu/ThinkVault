#!/usr/bin/env python3
"""
ThinkVault 模型下载脚本

从 ModelScope / HuggingFace 下载 GGUF 模型到 ~/.thinkvault/models/ 目录。
默认使用 ModelScope（国内镜像），可通过 --source hf 切换到 HuggingFace。

用法:
    python scripts/download_model.py                           # 下载默认模型 (Qwen2.5-0.5B-Instruct Q4_K_M)
    python scripts/download_model.py --model qwen2.5-3b        # 下载指定模型
    python scripts/download_model.py --source hf              # 使用 HuggingFace 源
    python scripts/download_model.py --list                    # 列出可用模型
    python scripts/download_model.py --dir /path/to/models     # 指定下载目录
"""

import argparse
import os
import sys
from pathlib import Path


# 下载源配置
DOWNLOAD_SOURCES = {
    "modelscope": {
        "name": "ModelScope（国内镜像）",
        "url_pattern": "https://modelscope.cn/models/{org}/{repo}/resolve/master/{filename}",
        "org_map": {
            "qwen2.5": "qwen/Qwen2.5-0.5B-Instruct-GGUF",
        },
    },
    "hf": {
        "name": "HuggingFace",
        "url_pattern": "https://huggingface.co/{org}/{repo}/resolve/main/{filename}",
        "org_map": {
            "qwen2.5": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        },
    },
}

DEFAULT_SOURCE = "modelscope"

# 可用模型列表 (name → 下载信息)
AVAILABLE_MODELS = {
    "qwen2.5-0.5b": {
        "filename": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "size_mb": 400,
        "description": "Qwen2.5 0.5B Instruct (Q4_K_M 量化, ~0.4GB)",
        "source_key": "qwen2.5",
        "repo_map": {
            "modelscope": "qwen/Qwen2.5-0.5B-Instruct-GGUF",
            "hf": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        },
    },
    "qwen2.5-1.5b": {
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "size_mb": 1000,
        "description": "Qwen2.5 1.5B Instruct (Q4_K_M 量化, ~1.0GB)",
        "source_key": "qwen2.5",
        "repo_map": {
            "modelscope": "qwen/Qwen2.5-1.5B-Instruct-GGUF",
            "hf": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        },
    },
    "qwen2.5-3b": {
        "filename": "qwen2.5-3b-instruct-q4_k_m.gguf",
        "size_mb": 2000,
        "description": "Qwen2.5 3B Instruct (Q4_K_M 量化, ~2.0GB) — RAG 推荐最低配置",
        "source_key": "qwen2.5",
        "repo_map": {
            "modelscope": "qwen/Qwen2.5-3B-Instruct-GGUF",
            "hf": "Qwen/Qwen2.5-3B-Instruct-GGUF",
        },
    },
    "qwen2.5-7b": {
        "filename": "qwen2.5-7b-instruct-q4_k_m.gguf",
        "size_mb": 4700,
        "description": "Qwen2.5 7B Instruct (Q4_K_M 量化, ~4.7GB) — RAG 甜点模型",
        "source_key": "qwen2.5",
        "repo_map": {
            "modelscope": "qwen/Qwen2.5-7B-Instruct-GGUF",
            "hf": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        },
    },
    "qwen2.5-14b": {
        "filename": "qwen2.5-14b-instruct-q4_k_m.gguf",
        "size_mb": 9000,
        "description": "Qwen2.5 14B Instruct (Q4_K_M 量化, ~9GB) — 高质量模型",
        "source_key": "qwen2.5",
        "repo_map": {
            "modelscope": "qwen/Qwen2.5-14B-Instruct-GGUF",
            "hf": "Qwen/Qwen2.5-14B-Instruct-GGUF",
        },
    },
    "qwen2.5-32b": {
        "filename": "qwen2.5-32b-instruct-q4_k_m.gguf",
        "size_mb": 20000,
        "description": "Qwen2.5 32B Instruct (Q4_K_M 量化, ~20GB) — 旗舰模型",
        "source_key": "qwen2.5",
        "repo_map": {
            "modelscope": "qwen/Qwen2.5-32B-Instruct-GGUF",
            "hf": "Qwen/Qwen2.5-32B-Instruct-GGUF",
        },
    },
}

DEFAULT_MODEL = "qwen2.5-0.5b"


def get_default_model_dir() -> Path:
    """获取默认模型目录"""
    home = Path.home()
    model_dir = home / ".thinkvault" / "models"
    return model_dir


def list_models():
    """列出所有可用模型"""
    print("可用模型列表:")
    print("-" * 70)
    for key, info in AVAILABLE_MODELS.items():
        default_tag = " [默认]" if key == DEFAULT_MODEL else ""
        print(f"  {key}{default_tag}")
        print(f"    文件: {info['filename']}")
        print(f"    大小: ~{info['size_mb']}MB")
        print(f"    说明: {info['description']}")
        print()


def build_url(model_key: str, source: str) -> str:
    """根据模型和源构建下载 URL"""
    info = AVAILABLE_MODELS[model_key]
    filename = info["filename"]
    repo = info["repo_map"][source]
    src = DOWNLOAD_SOURCES[source]
    return src["url_pattern"].format(org="", repo=repo, filename=filename)


def download_model(model_key: str, model_dir: Path, source: str = DEFAULT_SOURCE):
    """下载指定模型"""
    if model_key not in AVAILABLE_MODELS:
        print(f"错误: 未知模型 '{model_key}'")
        print(f"可用模型: {', '.join(AVAILABLE_MODELS.keys())}")
        sys.exit(1)

    if source not in DOWNLOAD_SOURCES:
        print(f"错误: 未知下载源 '{source}'")
        print(f"可用源: {', '.join(DOWNLOAD_SOURCES.keys())}")
        sys.exit(1)

    info = AVAILABLE_MODELS[model_key]
    filename = info["filename"]
    url = build_url(model_key, source)
    expected_size_mb = info["size_mb"]
    target_path = model_dir / filename
    source_name = DOWNLOAD_SOURCES[source]["name"]

    # 检查是否已存在
    if target_path.exists():
        actual_size_mb = target_path.stat().st_size / (1024 * 1024)
        # 简单校验：文件大小是否在预期范围（允许 ±20% 偏差）
        if actual_size_mb > expected_size_mb * 0.5:
            print(f"模型已存在: {target_path} ({actual_size_mb:.1f}MB)")
            print("如需重新下载，请先删除该文件。")
            return target_path

    # 创建目录
    model_dir.mkdir(parents=True, exist_ok=True)

    print(f"开始下载模型: {info['description']}")
    print(f"  来源: {source_name}")
    print(f"  URL: {url}")
    print(f"  目标: {target_path}")
    print(f"  预计大小: ~{expected_size_mb}MB")
    print()

    try:
        import httpx
    except ImportError:
        print("错误: 需要 httpx 库，请运行: pip install httpx")
        sys.exit(1)

    # 使用流式下载 + 进度显示
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=600) as resp:
            resp.raise_for_status()
            total_size = int(resp.headers.get("content-length", 0))
            downloaded = 0

            with open(target_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = downloaded / total_size * 100
                        mb = downloaded / (1024 * 1024)
                        total_mb = total_size / (1024 * 1024)
                        # 用 \r 覆盖同一行显示进度
                        sys.stdout.write(f"\r  下载进度: {mb:.1f}/{total_mb:.1f}MB ({pct:.1f}%)")
                        sys.stdout.flush()

        print()  # 换行

        # 验证文件大小
        actual_size_mb = target_path.stat().st_size / (1024 * 1024)
        if actual_size_mb < expected_size_mb * 0.5:
            print(f"警告: 下载文件大小 ({actual_size_mb:.1f}MB) 远小于预期 ({expected_size_mb}MB)")
            print("文件可能不完整，建议重新下载。")
            target_path.unlink(missing_ok=True)
            sys.exit(1)

        print(f"下载完成: {target_path} ({actual_size_mb:.1f}MB)")
        print()
        print("启动推理服务:")
        print(f"  python -m llama_cpp.server --model {target_path} --port 8080")

        return target_path

    except httpx.HTTPStatusError as e:
        print(f"\n下载失败: HTTP {e.response.status_code}")
        target_path.unlink(missing_ok=True)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n下载已取消")
        target_path.unlink(missing_ok=True)
        sys.exit(1)
    except Exception as e:
        print(f"\n下载失败: {e}")
        target_path.unlink(missing_ok=True)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="ThinkVault 模型下载工具 — 从 ModelScope/HuggingFace 下载 GGUF 模型",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"可用模型: {', '.join(AVAILABLE_MODELS.keys())}\n默认模型: {DEFAULT_MODEL}\n默认源: {DOWNLOAD_SOURCES[DEFAULT_SOURCE]['name']}",
    )
    parser.add_argument(
        "--model", "-m",
        default=DEFAULT_MODEL,
        help=f"要下载的模型名称 (默认: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--source", "-s",
        default=DEFAULT_SOURCE,
        choices=list(DOWNLOAD_SOURCES.keys()),
        help=f"下载源 (默认: {DEFAULT_SOURCE}, 可选: hf)",
    )
    parser.add_argument(
        "--dir", "-d",
        default=None,
        help="模型保存目录 (默认: ~/.thinkvault/models/)",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="列出所有可用模型",
    )

    args = parser.parse_args()

    if args.list:
        list_models()
        return

    model_dir = Path(args.dir) if args.dir else get_default_model_dir()
    download_model(args.model, model_dir, source=args.source)


if __name__ == "__main__":
    main()
