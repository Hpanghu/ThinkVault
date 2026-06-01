#!/usr/bin/env python3
"""
ThinkVault 一键打包脚本
用法:
    python build.py          # 默认：单文件 EXE（目录模式，生成文件夹含所有依赖）
    python build.py --onefile # 单文件 EXE（压缩到一个 .exe）
    python build.py --clean  # 清理构建产物
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
SPEC_FILE = PROJECT_ROOT / "ThinkVault.spec"

APP_NAME = "ThinkVault"
ENTRY_POINT = str(PROJECT_ROOT / "thinkvault" / "api" / "server.py")
ICON_PATH = str(PROJECT_ROOT / "thinkvault" / "webui" / "favicon.ico")

# PyInstaller 隐藏导入（动态加载的模块需要显式声明）
HIDDEN_IMPORTS = [
    "chromadb",
    "chromadb.api",
    "chromadb.config",
    "chromadb.utils.embedding_functions",
    "sentence_transformers",
    "sentence_transformers.models",
    "pymupdf",
    "docx",
    "openpyxl",
    "pptx",
    "httpx",
    "httpx._models",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "fastapi",
    "starlette",
]

# 额外数据文件 (source -> dest_dir)
DATAS = [
    # WebUI 静态文件
    (str(PROJECT_ROOT / "thinkvault" / "webui"), "thinkvault/webui"),
    # 版本文件
    (str(PROJECT_ROOT / "pyproject.toml"), "."),
]


def clean():
    """清理构建产物"""
    for p in [DIST_DIR, BUILD_DIR, SPEC_FILE]:
        if p.exists():
            if p.is_dir():
                shutil.rmtree(p)
                print(f"[CLEAN] 已删除 {p}")
            else:
                p.unlink()
                print(f"[CLEAN] 已删除 {p}")

    # 清理 __pycache__
    for pycache in PROJECT_ROOT.rglob("__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)
    print("[CLEAN] 构建产物已清理")


def build(onefile=False):
    """运行 PyInstaller 构建"""
    if not shutil.which("pyinstaller"):
        print("[BUILD] 安装 PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller>=6.0"])

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--clean",
        "--noconfirm",
    ]

    if onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    # 控制台窗口
    cmd.append("--console")

    # 图标
    if os.path.exists(ICON_PATH):
        cmd.extend(["--icon", ICON_PATH])

    # 隐藏导入
    for imp in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", imp])

    # 排除不必要的重型模块
    excludes = [
        "tkinter", "matplotlib", "numpy.tests", "scipy",
        "pandas.tests", "PIL.ImageQt", "IPython", "jupyter",
        "notebook", "sphinx", "pytest", "setuptools",
    ]
    for exc in excludes:
        cmd.extend(["--exclude-module", exc])

    # 数据文件
    for src, dest in DATAS:
        if os.path.exists(src):
            separator = ";" if sys.platform == "win32" else ":"
            cmd.extend(["--add-data", f"{src}{separator}{dest}"])

    # 入口
    cmd.append(ENTRY_POINT)

    # 收集额外数据目录
    cmd.extend(["--collect-data", "chromadb"])
    cmd.extend(["--collect-data", "sentence_transformers"])

    print(f"[BUILD] {'单文件' if onefile else '目录'}模式构建中...")
    print(f"[BUILD] 命令: {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode == 0:
        out = DIST_DIR / APP_NAME
        if onefile:
            out = DIST_DIR / f"{APP_NAME}.exe" if sys.platform == "win32" else DIST_DIR / APP_NAME
        print(f"[BUILD] 构建成功！输出: {out}")
    else:
        print(f"[BUILD] 构建失败 (exit code: {result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description="ThinkVault 打包工具")
    parser.add_argument("--onefile", action="store_true", help="生成单文件 EXE")
    parser.add_argument("--clean", action="store_true", help="清理构建产物")
    args = parser.parse_args()

    if args.clean:
        clean()
    else:
        build(onefile=args.onefile)


if __name__ == "__main__":
    main()