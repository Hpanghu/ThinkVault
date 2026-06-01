# -*- coding: utf-8 -*-
"""
Qwen2.5-7B-Instruct Q4_K_M GGUF 下载脚本
目标：D:\\DMX\\qwen2.5-7b-instruct-q4_k_m.gguf
来源：ModelScope（国内镜像，稳定快速）
"""
import os
import sys
import time
import io
import urllib.request

# 强制 stdout 使用 utf-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SAVE_DIR = r"D:\DMX"
FILE_NAME = "qwen2.5-7b-instruct-q4_k_m.gguf"
SAVE_PATH = os.path.join(SAVE_DIR, FILE_NAME)

# ModelScope 直链
DOWNLOAD_URL = (
    "https://modelscope.cn/api/v1/models/Qwen/Qwen2.5-7B-Instruct-GGUF/"
    "repo?FilePath=qwen2.5-7b-instruct-q4_k_m.gguf"
)

def format_size(bytes_val):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} TB"

def download_with_progress(url, save_path):
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    
    # 支持断点续传
    resume_pos = 0
    if os.path.exists(save_path):
        resume_pos = os.path.getsize(save_path)
        print(f"[续传] 已下载 {format_size(resume_pos)}, 继续下载...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }
    if resume_pos > 0:
        headers["Range"] = f"bytes={resume_pos}-"
    
    req = urllib.request.Request(url, headers=headers)
    
    with urllib.request.urlopen(req, timeout=60) as response:
        total_size = int(response.headers.get("Content-Length", 0)) + resume_pos
        
        mode = "ab" if resume_pos > 0 else "wb"
        downloaded = resume_pos
        start_time = time.time()
        block_size = 1024 * 1024  # 1MB chunks
        
        print(f"\n开始下载: {FILE_NAME}")
        print(f"总大小: {format_size(total_size)}")
        print(f"保存至: {save_path}\n")
        
        with open(save_path, mode) as f:
            while True:
                chunk = response.read(block_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                
                # 进度显示
                elapsed = time.time() - start_time
                speed = (downloaded - resume_pos) / elapsed if elapsed > 0 else 0
                progress = (downloaded / total_size * 100) if total_size > 0 else 0
                eta = (total_size - downloaded) / speed if speed > 0 else 0
                
                bar_len = 40
                filled = int(bar_len * downloaded / total_size) if total_size > 0 else 0
                bar = "#" * filled + "-" * (bar_len - filled)
                
                print(
                    f"\r[{bar}] {progress:.1f}% "
                    f"{format_size(downloaded)}/{format_size(total_size)} "
                    f"@ {format_size(speed)}/s "
                    f"ETA: {eta:.0f}s",
                    end="", flush=True
                )
        
        print(f"\n\n[OK] 下载完成! 文件: {save_path}")
        print(f"文件大小: {format_size(os.path.getsize(save_path))}")


if __name__ == "__main__":
    print("=" * 60)
    print("HybridMind 模型下载器")
    print("模型: Qwen2.5-7B-Instruct Q4_K_M (GGUF)")
    print("=" * 60)
    
    try:
        download_with_progress(DOWNLOAD_URL, SAVE_PATH)
    except KeyboardInterrupt:
        print("\n\n[PAUSE] 下载已暂停，下次运行将自动续传")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] 下载失败: {e}")
        print("请尝试手动从以下地址下载:")
        print(f"  {DOWNLOAD_URL}")
        sys.exit(1)
