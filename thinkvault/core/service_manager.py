"""本地服务管理器 — 管理 llama-cpp-python server 等子进程的生命周期

提供一键启动/停止本地推理服务的能力，包括：
- 自动发现本地 GGUF 模型文件
- 启动 llama-cpp-python server 子进程
- 健康检查与状态监控
- 优雅停止与超时清理
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Dict, List

from thinkvault.utils.logger import logger


class ServiceInfo:
    """单个服务的状态信息"""

    def __init__(self, name: str, display_name: str):
        self.name = name
        self.display_name = display_name
        self.status: str = "stopped"  # stopped | starting | running | error
        self.message: str = ""
        self.pid: Optional[int] = None
        self.process: Optional[subprocess.Popen] = None
        self.start_time: Optional[float] = None
        self.port: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "status": self.status,
            "message": self.message,
            "pid": self.pid,
            "port": self.port,
            "uptime_sec": round(time.time() - self.start_time, 1) if self.start_time else 0,
        }


class ServiceManager:
    """管理本地推理服务的生命周期"""

    def __init__(self):
        self._services: Dict[str, ServiceInfo] = {}
        self._lock = threading.Lock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = False

    def _ensure_monitor(self):
        """确保后台监控线程运行"""
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            return
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="service-monitor"
        )
        self._monitor_thread.start()

    def _monitor_loop(self):
        """后台监控线程 — 检测子进程退出"""
        while self._running:
            with self._lock:
                for svc in self._services.values():
                    if svc.process is not None and svc.status == "running":
                        ret = svc.process.poll()
                        if ret is not None:
                            svc.status = "error"
                            svc.message = f"进程已退出 (code={ret})"
                            svc.pid = None
                            svc.process = None
                            logger.warning(f"服务 {svc.name} 异常退出: code={ret}")
            time.sleep(2)

    def stop_monitor(self):
        """停止监控线程"""
        self._running = False

    def list_local_models(self) -> List[dict]:
        """扫描本地模型目录，返回可用 GGUF 模型列表"""
        model_dir = Path(os.path.expanduser("~/.thinkvault/models"))
        models = []
        if model_dir.is_dir():
            for f in sorted(model_dir.glob("*.gguf")):
                size_mb = f.stat().st_size / (1024 * 1024)
                models.append({
                    "id": f.name,
                    "name": f.name,
                    "size_mb": round(size_mb, 1),
                    "path": str(f),
                })
        return models

    async def start_llama_server(
        self,
        model_path: str,
        port: int = 8080,
        n_ctx: int = 2048,
        host: str = "127.0.0.1",
        n_gpu_layers: int = 0,
    ) -> dict:
        """启动 llama-cpp-python server 子进程

        Args:
            model_path: GGUF 模型文件路径
            port: 服务端口
            n_ctx: 上下文长度
            host: 监听地址
            n_gpu_layers: GPU 层数 (0=纯CPU)

        Returns:
            启动结果 dict
        """
        svc_name = "llama-server"
        with self._lock:
            if svc_name in self._services:
                svc = self._services[svc_name]
                if svc.status == "running":
                    return {"status": "already_running", "message": "推理服务已在运行", "port": svc.port}

        # 检查端口是否已被占用（可能已有 llama-cpp 服务在运行）
        import httpx
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"http://{host}:{port}/v1/models")
                if resp.status_code == 200:
                    # 端口上已有服务在运行，无需启动新进程
                    svc = ServiceInfo(svc_name, "推理服务 (llama-cpp)")
                    svc.status = "running"
                    svc.message = "检测到已有推理服务运行中"
                    svc.port = port
                    svc.start_time = time.time()
                    with self._lock:
                        self._services[svc_name] = svc
                    return {"status": "already_running", "message": "检测到已有推理服务运行中", "port": port}
        except Exception:
            logger.debug("端口 %s:%s 未被占用，继续启动", host, port, exc_info=True)

        # 验证模型文件存在
        model_file = Path(model_path)
        if not model_file.exists():
            return {"status": "error", "message": f"模型文件不存在: {model_path}"}

        # 构建启动命令
        cmd = [
            sys.executable, "-m", "llama_cpp.server",
            "--model", str(model_file),
            "--port", str(port),
            "--n_ctx", str(n_ctx),
            "--host", host,
        ]
        if n_gpu_layers > 0:
            cmd.extend(["--n_gpu_layers", str(n_gpu_layers)])

        logger.info(f"启动推理服务: {' '.join(cmd)}")

        svc = ServiceInfo(svc_name, "推理服务 (llama-cpp)")
        svc.status = "starting"
        svc.message = "正在启动推理服务..."
        svc.port = port

        with self._lock:
            self._services[svc_name] = svc

        self._ensure_monitor()

        # 在后台线程中启动子进程
        def _start_process():
            try:
                # Windows 下创建新进程组，避免 Ctrl+C 传播
                kwargs = {}
                if sys.platform == "win32":
                    kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                else:
                    kwargs["start_new_session"] = True

                # 将日志输出到文件，避免 PIPE 缓冲区满导致子进程挂起
                log_dir = Path(os.path.expanduser("~/.thinkvault/logs"))
                log_dir.mkdir(parents=True, exist_ok=True)
                log_file = log_dir / "llama-server.log"
                log_fh = open(log_file, "w", encoding="utf-8")

                proc = subprocess.Popen(
                    cmd,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    **kwargs,
                )
                svc.process = proc
                svc.pid = proc.pid
                svc._log_fh = log_fh  # 保持文件句柄打开
                logger.info(f"推理服务进程已启动: PID={proc.pid}, 日志: {log_file}")
            except FileNotFoundError:
                svc.status = "error"
                svc.message = "llama-cpp-python 未安装，请运行: pip install llama-cpp-python"
                logger.error("llama-cpp-python 未安装")
            except Exception as e:
                svc.status = "error"
                svc.message = f"启动失败: {e}"
                logger.error(f"启动推理服务失败: {e}")

        thread = threading.Thread(target=_start_process, daemon=True)
        thread.start()
        thread.join(timeout=5)

        # 等待服务就绪（健康检查）— 当前已在 async 上下文中，直接 await
        if svc.status == "starting":
            ready = await self._wait_for_ready(host, port, timeout=60)
            if ready:
                svc.status = "running"
                svc.message = "推理服务运行中"
                svc.start_time = time.time()
                logger.info(f"推理服务已就绪: http://{host}:{port}")
            else:
                # 检查进程是否还在运行
                if svc.process and svc.process.poll() is None:
                    svc.status = "running"
                    svc.message = "推理服务启动中（尚未响应健康检查）"
                    svc.start_time = time.time()
                else:
                    svc.status = "error"
                    svc.message = "推理服务启动超时，请检查日志"
                    logger.error("推理服务启动超时")

        return {
            "status": svc.status,
            "message": svc.message,
            "port": svc.port,
            "pid": svc.pid,
        }

    async def _wait_for_ready(self, host: str, port: int, timeout: int = 30) -> bool:
        """等待服务就绪 — 轮询 /v1/models 端点"""
        import httpx
        url = f"http://{host}:{port}/v1/models"
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        return True
            except Exception:
                logger.debug("健康检查请求失败: %s:%s", host, port, exc_info=True)
            await asyncio.sleep(1)
        return False

    async def stop_service(self, name: str = "llama-server") -> dict:
        """停止指定服务"""
        with self._lock:
            svc = self._services.get(name)
            if not svc or svc.status not in ("running", "starting"):
                return {"status": "ok", "message": "服务未运行"}

        logger.info(f"正在停止服务: {name}")
        try:
            if svc.process and svc.process.poll() is None:
                if sys.platform == "win32":
                    # Windows: 优雅终止进程组
                    try:
                        svc.process.terminate()
                    except Exception:
                        pass
                    try:
                        svc.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        svc.process.kill()
                        svc.process.wait(timeout=3)
                else:
                    svc.process.terminate()
                    try:
                        svc.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        svc.process.kill()
                        svc.process.wait(timeout=3)

            svc.status = "stopped"
            svc.message = "服务已停止"
            svc.pid = None
            svc.process = None
            # 关闭日志文件句柄，防止资源泄漏
            if hasattr(svc, '_log_fh') and svc._log_fh:
                try:
                    svc._log_fh.close()
                except Exception:
                    pass
                svc._log_fh = None
            logger.info(f"服务 {name} 已停止")
            return {"status": "ok", "message": "服务已停止"}
        except Exception as e:
            svc.status = "error"
            svc.message = f"停止失败: {e}"
            return {"status": "error", "message": str(e)}

    async def stop_all(self) -> dict:
        """停止所有服务"""
        results = {}
        with self._lock:
            names = list(self._services.keys())
        for name in names:
            results[name] = await self.stop_service(name)
        return {"status": "ok", "results": results}

    def get_status(self) -> dict:
        """获取所有服务状态"""
        with self._lock:
            services = {name: svc.to_dict() for name, svc in self._services.items()}
        return {
            "services": services,
            "total": len(services),
            "running": sum(1 for s in services.values() if s["status"] == "running"),
        }

    def get_service(self, name: str) -> Optional[ServiceInfo]:
        """获取指定服务信息"""
        with self._lock:
            return self._services.get(name)


# 全局单例
service_manager = ServiceManager()
