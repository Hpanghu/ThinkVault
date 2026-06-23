"""
ThinkVault V2.0 一键启动脚本
自动检查依赖、推理后端（llama-cpp-python server），启动后端服务并打开浏览器
"""

import os
import sys
import threading
import webbrowser
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000


def check_python():
    print("[1/4] 检查 Python 版本...")
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 10):
        print(f"  错误: 需要 Python 3.10+，当前版本 {major}.{minor}")
        sys.exit(1)
    print(f"  通过: Python {major}.{minor}")


def check_dependencies():
    print("[2/4] 检查关键依赖...")
    deps = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "chromadb": "chromadb",
        "sentence_transformers": "sentence-transformers",
        "torch": "torch",
        "httpx": "httpx",
        "fitz": "pymupdf",
        "docx": "python-docx",
    }

    missing = []
    for module, package in deps.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        print(f"  缺失依赖: {', '.join(missing)}")
        print(f"  请运行: pip install {' '.join(missing)}")
        response = input("  是否继续启动？(y/n): ").strip().lower()
        if response != 'y':
            sys.exit(1)
    else:
        print("  通过: 所有关键依赖已安装")


def check_llm_backend():
    """检测推理后端（llama-cpp-python server）是否可用"""
    print("[3/4] 检查推理后端 (llama-cpp-python server)...")

    url = os.environ.get("THINKVAULT_LLM_URL", "http://localhost:8080/v1")

    # 尝试 OpenAI 兼容端点
    try:
        import urllib.request
        req = urllib.request.Request(f"{url}/models", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                import json as _json
                data = _json.loads(resp.read().decode())
                model_list = [m.get("id", "unknown") for m in data.get("data", [])]
                if model_list:
                    print(f"  通过: OpenAI 兼容 API 已就绪，可用模型: {', '.join(model_list[:5])}")
                    return
    except Exception:
        pass

    print(f"  警告: 无法连接推理后端 ({url})")
    print(f"  请确认 llama-cpp-python server 已安装并运行：")
    print(f"    1. 安装: pip install 'llama-cpp-python[server]'")
    print(f"    2. 下载模型到 ~/.thinkvault/models/ 目录")
    print(f"    3. 启动: python -m llama_cpp.server --model ~/.thinkvault/models/xxx.gguf --port 8080")
    print(f"  服务仍将启动，但对话将降级为仅检索模式。")


def main():
    print("=" * 60)
    print("  ThinkVault V2.0 — 个人 AI 工作台")
    print("=" * 60)

    check_python()
    check_dependencies()
    check_llm_backend()

    print("[4/4] 启动服务...")
    print(f"  后端: http://{SERVER_HOST}:{SERVER_PORT}")
    print(f"  前端: http://{SERVER_HOST}:{SERVER_PORT}/")
    print("  按 Ctrl+C 停止服务")
    print()

    def open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://{SERVER_HOST}:{SERVER_PORT}/")

    threading.Thread(target=open_browser, daemon=True).start()

    from thinkvault.api.server import run_server
    run_server(host=SERVER_HOST, port=SERVER_PORT)


if __name__ == "__main__":
    main()
