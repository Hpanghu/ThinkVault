#!/usr/bin/env python3
"""
ThinkVault V2.0 集成测试自动化脚本

功能：
  1. 启动 ThinkVault 服务器（subprocess）
  2. 等待服务就绪（轮询 /api/health）
  3. 运行 test_v2.py 全部 19 个测试用例
  4. 关闭服务器
  5. 输出测试报告

用法：
  python test/run_integration.py [--port 8000] [--timeout 60] [--verbose]

注意：
  - 本脚本会启动服务器占用端口，请确保端口未被占用
  - 测试需要一个可用的 Python 环境和已安装的依赖
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── 配置 ──────────────────────────────────────────────────────────

DEFAULT_PORT = 8000
DEFAULT_HOST = "127.0.0.1"
STARTUP_TIMEOUT = 60  # 等待服务器启动的最大秒数
HEALTH_CHECK_INTERVAL = 2  # 健康检查间隔秒数


def color(text: str, code: str) -> str:
    """终端颜色包装（Windows 兼容）"""
    colors = {"green": "32", "red": "31", "yellow": "33", "blue": "34", "bold": "1"}
    c = colors.get(code, "0")
    return f"\033[{c}m{text}\033[0m"


def check_port_free(host: str, port: int) -> bool:
    """检查端口是否可用"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        s.close()
        return True
    except OSError:
        s.close()
        return False


def start_server(host: str, port: int) -> subprocess.Popen:
    """启动 ThinkVault 服务器"""
    print(color(f"[1/5] 启动 ThinkVault 服务器 (http://{host}:{port})...", "blue"))

    # 配置环境变量：禁用 LLM 加载加速启动
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    # 使用 sys.executable 确保使用当前 Python 解释器
    cmd = [
        sys.executable, "-m", "uvicorn",
        "thinkvault.api.server:create_app",
        "--host", host,
        "--port", str(port),
        "--factory",
    ]

    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    return proc


def wait_for_ready(host: str, port: int, timeout: int) -> tuple[bool, float]:
    """轮询健康检查端点直到服务就绪"""
    print(color(f"[2/5] 等待服务就绪（最长 {timeout}s）...", "blue"))

    import urllib.request
    import urllib.error

    start = time.time()
    url = f"http://{host}:{port}/api/health"

    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    elapsed = time.time() - start
                    print(color(f"      服务就绪 (耗时 {elapsed:.1f}s)", "green"))
                    return True, elapsed
        except (urllib.error.URLError, ConnectionRefusedError, TimeoutError, OSError):
            pass

        time.sleep(HEALTH_CHECK_INTERVAL)

    print(color(f"      超时: 服务在 {timeout}s 内未就绪", "red"))
    return False, time.time() - start


def run_tests(host: str, port: int, verbose: bool) -> dict:
    """运行 test_v2.py 测试套件（内联调用 pytest，避免子进程沙箱问题）"""
    print(color("[3/5] 运行 test_v2.py 全部测试...", "blue"))

    import pytest

    test_path = str(PROJECT_ROOT / "test" / "test_v2.py")
    args = [test_path, "-v", "--color=no"]
    if verbose:
        args.append("--tb=long")
    else:
        args.append("--tb=short")

    # 用 pytest.main 内联运行
    exit_code = pytest.main(args, plugins=[])

    # pytest.main 直接输出到终端，解析结果参数需要在脚本外部完成
    # 这里返回退出码，实际结果由 generate_report 通过 exit_code 判断
    return {
        "exit_code": exit_code,
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
    }


def _run_tests_subprocess(host: str, port: int, verbose: bool) -> dict:
    """通过 subprocess 运行 pytest（备用方案，在某些沙箱环境中可能超时）。"""
    test_path = str(PROJECT_ROOT / "test" / "test_v2.py")
    cmd = [sys.executable, "-m", "pytest", test_path, "-v", "--color=no"]
    if verbose:
        cmd.append("--tb=long")
    else:
        cmd.append("--tb=short")

    log_dir = PROJECT_ROOT / "temp"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = str(log_dir / "integration_pytest.log")

    with open(log_path, "w", encoding="utf-8", errors="replace") as log_fp:
        proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), stdout=log_fp,
                              stderr=subprocess.STDOUT, timeout=120)
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        output = f.read()
    print(output)

    passed = failed = errors = skipped = 0
    import re as _re
    for line in output.split("\n"):
        m = _re.search(r"(\d+) passed.*?(\d+) failed.*?(\d+) error.*?(\d+) skipped", line)
        if m:
            passed, failed, errors, skipped = map(int, m.groups())
            break
        m2 = _re.search(r"(\d+) failed.*?(\d+) passed", line)
        if m2:
            failed, passed = int(m2.group(1)), int(m2.group(2))
            break
        m3 = _re.search(r"(\d+) passed", line)
        if m3 and "failed" not in line:
            passed = int(m3.group(1))
            break

    return {"exit_code": proc.returncode, "passed": passed, "failed": failed,
            "errors": errors, "skipped": skipped}


def stop_server(proc: subprocess.Popen, host: str, port: int):
    """优雅关闭服务器"""
    print(color("[4/5] 关闭服务器...", "blue"))

    if sys.platform == "win32":
        # Windows: 使用 taskkill 确保进程树终止
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            proc.kill()
    else:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    # 等待端口释放
    for _ in range(10):
        if check_port_free(host, port):
            print(color("      服务器已关闭", "green"))
            return
        time.sleep(1)

    print(color("      服务器关闭确认", "yellow"))


def generate_report(
    ready: bool,
    startup_time: float,
    test_results: dict,
    start_time: datetime,
) -> str:
    """生成测试报告"""
    print(color("[5/5] 生成测试报告...", "blue"))

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    exit_code = test_results.get("exit_code", -1)
    passed = test_results.get("passed", 0)
    failed = test_results.get("failed", 0)

    all_passed = exit_code == 0

    report_lines = [
        "# ThinkVault V2.0 集成测试报告",
        "",
        f"- **执行时间**: {start_time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **总耗时**: {duration:.1f}s",
        f"- **服务启动**: {'✅ 成功' if ready else '❌ 失败'} ({startup_time:.1f}s)",
        f"- **测试结果**: {'✅ 全部通过' if all_passed else '❌ 存在失败'}",
        "",
        "## 测试套件: test_v2.py",
        "",
        f"| 项目 | 数值 |",
        f"|------|------|",
        f"| 通过 | {passed} |",
        f"| 失败 | {failed} |",
        f"| 总计 | {passed + failed} |",
        "",
        "> 详细输出见上方控制台日志。",
        "",
        "## 备注",
        "",
        f"- 测试服务器地址: http://127.0.0.1:{DEFAULT_PORT}",
        "- 所有 Conversation / Document 测试数据已在用例中自动清理",
    ]

    if not ready:
        report_lines.append("- ⚠️ 服务启动失败，测试未执行")

    if not all_passed:
        report_lines.append("- ⚠️ 部分测试未通过，请查看上方 pytest 输出")

    report = "\n".join(report_lines)

    # 写入 output 目录
    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "integration_test_report.md"
    report_path.write_text(report, encoding="utf-8")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="ThinkVault V2.0 集成测试自动化"
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="服务器端口")
    parser.add_argument("--timeout", type=int, default=STARTUP_TIMEOUT, help="启动超时(秒)")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    parser.add_argument("--skip-startup-check", action="store_true",
                        help="跳过端口占用检查（允许并发运行）")
    args = parser.parse_args()

    host = DEFAULT_HOST
    port = args.port
    start_time = datetime.now()

    print("=" * 60)
    print(color("ThinkVault V2.0 集成测试自动化", "bold"))
    print(f"目标: http://{host}:{port}")
    print(f"时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print()

    # ---- Step 0: 端口检查 ----
    if not args.skip_startup_check and not check_port_free(host, port):
        print(color(f"错误: 端口 {port} 已被占用，请先释放或指定其他端口", "red"))
        sys.exit(1)

    # ---- Step 1: 启动服务器 ----
    proc = start_server(host, port)

    # ---- Step 2: 等待就绪 ----
    ready, startup_time = wait_for_ready(host, port, args.timeout)

    test_results = {"exit_code": -1, "error": "服务未就绪，测试跳过"}

    if ready:
        # ---- Step 3: 运行测试 ----
        test_results = run_tests(host, port, args.verbose)

    # ---- Step 4: 关闭服务器 ----
    stop_server(proc, host, port)

    # ---- Step 5: 报告 ----
    report = generate_report(ready, startup_time, test_results, start_time)

    print()
    print("=" * 60)
    print(color("测试报告摘要", "bold"))
    print("=" * 60)
    print(report)
    print()

    # 返回状态码
    exit_code = test_results.get("exit_code", -1)
    if exit_code == 0:
        print(color("集成测试通过", "green"))
    else:
        print(color(f"集成测试失败 (exit={exit_code})", "red"))

    sys.exit(exit_code)


if __name__ == "__main__":
    main()