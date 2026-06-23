#!/usr/bin/env python3
"""
ThinkVault 端到端测试脚本 — Qwen2.5-0.5B 模型

使用 llama-server (OpenAI 兼容 API) + ThinkVault 后端进行完整的 RAG 流程测试。
无需启动 ThinkVault 服务，直接调用 API。

前置条件:
    1. 启动 llama-server:
       cd ~/.thinkvault/llama.cpp
       ./llama-server.exe --model ~/.thinkvault/models/qwen2.5-0.5b-instruct-q4_k_m.gguf --port 8080 --host 127.0.0.1 --ctx-size 2048 --threads 4

    2. 运行测试:
       python scripts/e2e_test.py

测试内容:
    1. LLM 基础推理（无 RAG）
    2. LLM 流式推理
    3. RAG 流程：创建知识库 → 上传文档 → 检索 → 生成回答
    4. 性能指标：延迟、吞吐量、内存占用
"""

import json
import os
import sys
import time
import tempfile
import argparse
from pathlib import Path
from datetime import datetime

# 确保 project root 在 path 中
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import httpx
except ImportError:
    print("错误: 需要 httpx 库")
    print("  pip install httpx")
    sys.exit(1)

# 配置
DEFAULT_LLM_URL = os.environ.get("THINKVAULT_LLM_URL", "http://localhost:8080/v1")
DEFAULT_API_URL = os.environ.get("THINKVAULT_API_URL", "http://localhost:8000")
API_TOKEN = os.environ.get("THINKVAULT_API_TOKEN", "B-tOnoFYbfZf76tb7H0BCfZAy1tddNICnEZNNaqAbSA")


class Colors:
    """终端颜色"""
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    END = "\033[0m"


def print_pass(msg):
    print(f"  {Colors.GREEN}✓{Colors.END} {msg}")


def print_fail(msg):
    print(f"  {Colors.RED}✗{Colors.END} {msg}")


def print_info(msg):
    print(f"  {Colors.CYAN}→{Colors.END} {msg}")


def print_header(msg):
    print(f"\n{Colors.BOLD}{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}{Colors.END}")


class E2ETestResult:
    """测试结果收集器"""

    def __init__(self):
        self.results = []
        self.start_time = time.time()

    def add(self, name, passed, latency_ms=None, details=None):
        self.results.append({
            "name": name,
            "passed": passed,
            "latency_ms": latency_ms,
            "details": details,
        })

    def summary(self):
        total = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        failed = total - passed
        elapsed = time.time() - self.start_time

        print_header("测试报告")
        print(f"  总测试数: {total}")
        print(f"  通过: {Colors.GREEN}{passed}{Colors.END}")
        print(f"  失败: {Colors.RED}{failed}{Colors.END}" if failed else "")
        print(f"  总耗时: {elapsed:.1f}s")
        print()

        for r in self.results:
            status = Colors.GREEN + "✓" + Colors.END if r["passed"] else Colors.RED + "✗" + Colors.END
            latency = f" ({r['latency_ms']:.0f}ms)" if r["latency_ms"] else ""
            print(f"  {status} {r['name']}{latency}")
            if r["details"] and not r["passed"]:
                print(f"      详情: {r['details']}")

        return passed == total


# ============================================================
# 阶段 1: LLM 基础连通性
# ============================================================

def test_llm_connectivity(base_url):
    """测试 LLM 服务是否可用"""
    print_header("阶段 1: LLM 服务连通性")

    results = E2ETestResult()

    # 1.1 检查 /v1/models
    try:
        t0 = time.time()
        resp = httpx.get(f"{base_url}/models", timeout=10)
        latency = (time.time() - t0) * 1000
        if resp.status_code == 200:
            data = resp.json()
            models = [m["id"] for m in data.get("data", [])]
            print_pass(f"模型列表: {', '.join(models)} ({latency:.0f}ms)")
            results.add("GET /v1/models", True, latency)
        else:
            print_fail(f"HTTP {resp.status_code}")
            results.add("GET /v1/models", False, latency, f"HTTP {resp.status_code}")
    except Exception as e:
        print_fail(f"连接失败: {e}")
        results.add("GET /v1/models", False, details=str(e))

    # 1.2 基础推理
    print_info("发送基础推理请求...")
    try:
        t0 = time.time()
        resp = httpx.post(
            f"{base_url}/chat/completions",
            json={
                "model": "default",
                "messages": [
                    {"role": "system", "content": "你是一个有用的助手。"},
                    {"role": "user", "content": "什么是RAG？请用一句话回答。"},
                ],
                "max_tokens": 200,
                "temperature": 0.3,
            },
            timeout=60,
        )
        latency = (time.time() - t0) * 1000
        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            usage = data.get("usage", {})
            print_pass(f"推理成功 ({latency:.0f}ms, {usage.get('prompt_tokens', '?')}+{usage.get('completion_tokens', '?')} tokens)")
            print_info(f"回答: {content[:200]}")
            results.add("基础推理 (非流式)", True, latency, {"answer": content[:200], "usage": usage})
        else:
            print_fail(f"HTTP {resp.status_code}: {resp.text[:200]}")
            results.add("基础推理 (非流式)", False, latency, f"HTTP {resp.status_code}")
    except Exception as e:
        print_fail(f"推理失败: {e}")
        results.add("基础推理 (非流式)", False, details=str(e))

    # 1.3 流式推理
    print_info("测试流式推理...")
    try:
        t0 = time.time()
        tokens = []
        with httpx.stream(
            "POST",
            f"{base_url}/chat/completions",
            json={
                "model": "default",
                "messages": [
                    {"role": "user", "content": "你好"},
                ],
                "max_tokens": 50,
                "temperature": 0.3,
                "stream": True,
            },
            timeout=60,
        ) as resp:
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0].get("delta", {})
                        token = delta.get("content", "")
                        if token:
                            tokens.append(token)
                    except (json.JSONDecodeError, IndexError, KeyError):
                        pass
        latency = (time.time() - t0) * 1000
        content = "".join(tokens)
        if content:
            tps = len(tokens) / (latency / 1000) if tokens else 0
            print_pass(f"流式推理成功 ({latency:.0f}ms, {len(tokens)} tokens, {tps:.1f} tokens/s)")
            print_info(f"回答: {content[:200]}")
            results.add("流式推理", True, latency, {"tokens": len(tokens), "tps": tps})
        else:
            print_fail("流式推理返回空内容")
            results.add("流式推理", False, latency, "empty response")
    except Exception as e:
        print_fail(f"流式推理失败: {e}")
        results.add("流式推理", False, details=str(e))

    return results


# ============================================================
# 阶段 2: RAG 流程测试
# ============================================================

def test_rag_flow(api_url, api_token, base_url):
    """测试完整 RAG 流程（需要 ThinkVault 服务运行）"""
    print_header("阶段 2: RAG 流程测试")

    results = E2ETestResult()
    headers = {"Authorization": f"Bearer {api_token}"}

    # 创建临时测试文档
    test_docs = {
        "ThinkVault技术架构.md": (
            "# ThinkVault 技术架构\n\n"
            "ThinkVault 是一个基于 Python FastAPI 构建的本地 RAG 系统。\n"
            "核心组件包括：\n"
            "1. 文档解析器 (parser.py) — 支持 PDF、DOCX、PPTX、XLSX、TXT、MD 等格式\n"
            "2. 文本分块器 (chunker.py) — 基于段落和语义的智能分块\n"
            "3. 向量嵌入器 (embedder.py) — 使用 sentence-transformers 模型\n"
            "4. 混合检索器 (retriever.py) — BM25 + 向量检索 + Rerank\n"
            "5. LLM 推理接口 (thinkvault_llm.py) — OpenAI 兼容 API\n"
            "6. 对话存储 (conversation_store.py) — SQLite 持久化\n"
            "\n"
            "RAG 流程：用户提问 → 意图判断 → 知识库检索 → 上下文组装 → LLM 生成 → 返回答案\n"
        ),
        "快速入门指南.md": (
            "# 快速入门\n\n"
            "1. 安装依赖: pip install -r requirements.txt\n"
            "2. 下载模型: python scripts/download_model.py\n"
            "3. 启动服务: python -m thinkvault.launch\n"
            "4. 打开浏览器: http://localhost:8000\n"
            "\n"
            "支持的文档格式：PDF、Word、Excel、PowerPoint、TXT、Markdown\n"
            "支持的知识库操作：创建、删除、列表、文档管理\n"
        ),
    }

    kb_name = f"e2e_test_{int(time.time())}"

    # 2.1 健康检查
    print_info("检查 ThinkVault API...")
    try:
        t0 = time.time()
        resp = httpx.get(f"{api_url}/api/health", headers=headers, timeout=10, params={"token": api_token})
        latency = (time.time() - t0) * 1000
        if resp.status_code == 200:
            print_pass(f"ThinkVault API 正常 ({latency:.0f}ms)")
            results.add("ThinkVault API 健康检查", True, latency)
        else:
            print_fail(f"HTTP {resp.status_code}")
            results.add("ThinkVault API 健康检查", False, latency, f"HTTP {resp.status_code}")
            print_info("⚠ ThinkVault API 不可用，跳过 RAG 流程测试")
            print_info("  启动命令: python -m thinkvault.launch")
            return results
    except Exception as e:
        print_fail(f"连接失败: {e}")
        results.add("ThinkVault API 健康检查", False, details=str(e))
        print_info("⚠ ThinkVault API 不可用，跳过 RAG 流程测试")
        return results

    # 2.2 创建知识库
    print_info(f"创建知识库: {kb_name}")
    try:
        t0 = time.time()
        resp = httpx.post(
            f"{api_url}/api/kb",
            headers=headers,
            json={"name": kb_name, "description": "E2E测试知识库"},
            timeout=10,
            params={"token": api_token},
        )
        latency = (time.time() - t0) * 1000
        if resp.status_code in (200, 201):
            kb_id = resp.json().get("id", kb_name)
            print_pass(f"知识库创建成功: {kb_id} ({latency:.0f}ms)")
            results.add("创建知识库", True, latency, {"kb_id": kb_id})
        else:
            print_fail(f"HTTP {resp.status_code}: {resp.text[:200]}")
            results.add("创建知识库", False, latency, f"HTTP {resp.status_code}")
            return results
    except Exception as e:
        print_fail(f"创建失败: {e}")
        results.add("创建知识库", False, details=str(e))
        return results

    # 2.3 上传文档
    print_info("上传测试文档...")
    uploaded_count = 0
    for filename, content in test_docs.items():
        try:
            t0 = time.time()
            # 使用 multipart 上传
            files = {"file": (filename, content.encode("utf-8"), "text/markdown")}
            resp = httpx.post(
                f"{api_url}/api/kb/{kb_id}/documents",
                headers=headers,
                files=files,
                timeout=30,
                params={"token": api_token},
            )
            latency = (time.time() - t0) * 1000
            if resp.status_code in (200, 201):
                uploaded_count += 1
                print_pass(f"上传成功: {filename} ({latency:.0f}ms)")
            else:
                print_fail(f"上传失败: {filename} (HTTP {resp.status_code})")
                results.add(f"上传文档 {filename}", False, latency, f"HTTP {resp.status_code}")
        except Exception as e:
            print_fail(f"上传异常: {filename} ({e})")
            results.add(f"上传文档 {filename}", False, details=str(e))

    if uploaded_count == len(test_docs):
        results.add(f"上传文档 (共{uploaded_count}个)", True)
    else:
        results.add(f"上传文档 ({uploaded_count}/{len(test_docs)})", False, details=f"部分上传失败")

    # 等待文档处理
    print_info("等待文档处理（3秒）...")
    time.sleep(3)

    # 2.4 RAG 聊天测试
    print_info("发送 RAG 聊天请求...")
    rag_questions = [
        "ThinkVault 的核心组件有哪些？",
        "如何启动 ThinkVault 服务？",
        "ThinkVault 支持哪些文档格式？",
    ]

    for q in rag_questions:
        try:
            t0 = time.time()
            resp = httpx.post(
                f"{api_url}/api/chat",
                headers=headers,
                json={
                    "message": q,
                    "kb_id": kb_id,
                    "stream": False,
                },
                timeout=60,
                params={"token": api_token},
            )
            latency = (time.time() - t0) * 1000
            if resp.status_code == 200:
                data = resp.json()
                answer = data.get("answer", data.get("response", "")).strip()
                sources = data.get("sources", [])
                print_pass(f"Q: {q} ({latency:.0f}ms)")
                print_info(f"A: {answer[:150]}...")
                if sources:
                    print_info(f"  检索来源: {len(sources)} 条")
                results.add(f"RAG: {q[:30]}...", True, latency, {"sources_count": len(sources)})
            else:
                print_fail(f"Q: {q} (HTTP {resp.status_code})")
                results.add(f"RAG: {q[:30]}...", False, latency, f"HTTP {resp.status_code}")
        except Exception as e:
            print_fail(f"Q: {q} ({e})")
            results.add(f"RAG: {q[:30]}...", False, details=str(e))

    # 2.5 清理：删除知识库
    print_info(f"清理知识库: {kb_id}")
    try:
        resp = httpx.delete(
            f"{api_url}/api/kb/{kb_id}",
            headers=headers,
            timeout=10,
            params={"token": api_token},
        )
        if resp.status_code in (200, 204):
            print_pass("知识库已删除")
        else:
            print_info(f"清理跳过 (HTTP {resp.status_code})")
    except Exception as e:
        print_info(f"清理异常: {e}")

    return results


# ============================================================
# 阶段 3: 性能基准
# ============================================================

def test_performance_benchmark(base_url):
    """运行性能基准测试"""
    print_header("阶段 3: 性能基准")

    results = E2ETestResult()

    prompts = [
        ("短问答", "你好"),
        ("中文问答", "中国的首都是哪里？"),
        ("RAG问答", "请解释什么是检索增强生成。"),
        ("代码生成", "写一个Python函数计算斐波那契数列。"),
    ]

    print_info("运行 4 轮推理性能测试...")
    total_tokens = 0
    total_time = 0

    for name, prompt in prompts:
        try:
            t0 = time.time()
            resp = httpx.post(
                f"{base_url}/chat/completions",
                json={
                    "model": "default",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 150,
                    "temperature": 0.3,
                },
                timeout=60,
            )
            latency = (time.time() - t0) * 1000
            if resp.status_code == 200:
                data = resp.json()
                usage = data.get("usage", {})
                completion_tokens = usage.get("completion_tokens", 0)
                prompt_tokens = usage.get("prompt_tokens", 0)
                total_tokens += completion_tokens
                total_time += latency / 1000

                tps = completion_tokens / (latency / 1000) if latency > 0 else 0
                print_pass(f"{name}: {latency:.0f}ms, {prompt_tokens}+{completion_tokens} tokens, {tps:.1f} t/s")
                results.add(f"性能: {name}", True, latency, {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "tps": tps,
                })
            else:
                print_fail(f"{name}: HTTP {resp.status_code}")
                results.add(f"性能: {name}", False, latency, f"HTTP {resp.status_code}")
        except Exception as e:
            print_fail(f"{name}: {e}")
            results.add(f"性能: {name}", False, details=str(e))

    if total_time > 0:
        avg_tps = total_tokens / total_time
        print_info(f"平均吞吐: {avg_tps:.1f} tokens/s")

    return results


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="ThinkVault 端到端测试 — Qwen2.5-0.5B",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--llm-url", default=DEFAULT_LLM_URL, help="LLM API URL")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="ThinkVault API URL")
    parser.add_argument("--token", default=API_TOKEN, help="API Token")
    parser.add_argument("--skip-rag", action="store_true", help="跳过 RAG 流程测试")
    args = parser.parse_args()

    print(f"\n{Colors.BOLD}ThinkVault E2E 测试{Colors.END}")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  LLM URL: {args.llm_url}")
    print(f"  API URL: {args.api_url}")
    print(f"  跳过 RAG: {args.skip_rag}")

    all_results = []

    # 阶段 1: LLM 基础测试
    llm_results = test_llm_connectivity(args.llm_url)
    all_results.append(llm_results)

    # 阶段 3: 性能基准
    perf_results = test_performance_benchmark(args.llm_url)
    all_results.append(perf_results)

    # 阶段 2: RAG 流程（可选）
    if not args.skip_rag:
        rag_results = test_rag_flow(args.api_url, args.token, args.llm_url)
        all_results.append(rag_results)

    # 汇总
    all_passed = all(r.summary() for r in all_results)
    total_passed = sum(sum(1 for r in res.results if r["passed"]) for res in all_results)
    total_tests = sum(len(res.results) for res in all_results)

    print_header("最终结果")
    if all_passed:
        print(f"  {Colors.GREEN}{Colors.BOLD}ALL {total_passed}/{total_tests} PASSED{Colors.END}")
    else:
        print(f"  {Colors.YELLOW}{total_passed}/{total_tests} PASSED{Colors.END} (部分测试失败)")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
