# ThinkVault 项目改进文档

> **版本**: v2.0.0 审计  
> **日期**: 2026-06-08  
> **审计范围**: 全栈代码、架构、安全、前端、测试、文档、依赖  
> **发现问题总数**: 50 项（严重 9 / 中等 23 / 低 18）

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [问题总览](#2-问题总览)
3. [代码质量问题](#3-代码质量问题)
4. [安全问题](#4-安全问题)
5. [前端问题](#5-前端问题)
6. [架构问题](#6-架构问题)
7. [测试覆盖问题](#7-测试覆盖问题)
8. [功能完整性问题](#8-功能完整性问题)
9. [文档与注释问题](#9-文档与注释问题)
10. [依赖与构建问题](#10-依赖与构建问题)
11. [优先修复路线图](#11-优先修复路线图)
12. [附录：完整问题清单](#12-附录完整问题清单)

---

## 1. 执行摘要

ThinkVault 是一款本地离线 RAG 知识库系统，核心定位为"知识馆长"——通过对话帮助用户在庞大知识库中精准检索文档。项目已完成 v2.0.0 迁移（从 GGUF 到 OpenAI 兼容 API），具备文档解析、混合检索、流式对话、知识库管理等核心功能。

本次审计发现 **50 个问题**，其中 **9 个严重**、**23 个中等**、**18 个低优先级**。最关键的风险集中在：

- **数据安全**：同名文件误删（向量/索引级）、API Token 硬编码泄露
- **离线一致性**：前端依赖 Google Fonts/CDN，与"完全离线"定位矛盾
- **架构债务**：6 个独立 SQLite 数据库、模块级单例与 IOC 容器冲突、Store 返回模块而非实例
- **安装门槛**：torch 作为核心依赖导致安装包约 2GB

建议按 **P0（阻断性）→ P1（重要）→ P2（改进）** 三级路线图推进修复，预计 P0 修复周期 1-2 天，P1 修复周期 1 周。

---

## 2. 问题总览

| 类别 | 严重 | 中等 | 低 | 合计 |
|------|:----:|:----:|:---:|:----:|
| 代码质量 | 2 | 4 | 6 | 12 |
| 安全问题 | 2 | 3 | 2 | 7 |
| 前端问题 | 1 | 3 | 2 | 6 |
| 架构问题 | 2 | 3 | 2 | 7 |
| 测试覆盖 | 1 | 2 | 0 | 3 |
| 功能完整性 | 0 | 3 | 3 | 6 |
| 文档质量 | 0 | 4 | 2 | 6 |
| 依赖构建 | 1 | 1 | 1 | 3 |
| **合计** | **9** | **23** | **18** | **50** |

---

## 3. 代码质量问题

### 3.1 [严重] URL 路径拼接 Bug

**文件**: `thinkvault/core/thinkvault_llm.py`

`_check_availability()` 中 `url = f"{self._base_url}/models"`，而 `self._base_url` 默认值为 `http://localhost:8080/v1`，实际请求路径变成 `/v1/models`。虽然 OpenAI 兼容 API 的 `/v1/models` 路径正确，但与 `generate()` 方法中拼接 `/chat/completions` 的模式不一致，且未使用 httpx Client 的 base_url 自动处理机制。

**改进方案**:
```python
# 改为使用 httpx.Client 的 base_url
self._client = httpx.Client(
    base_url=self._base_url,  # 自动处理路径拼接
    timeout=self._timeout,
    headers={"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
)

# 调用时只需相对路径
response = self._client.get("/models")
response = self._client.post("/chat/completions", json=payload)
```

### 3.2 [严重] 同名文件误删向量数据

**文件**: `thinkvault/core/incremental_indexer.py` (L291-298)、`thinkvault/api/routes/documents.py`

`collection.get(where={"source_file": file_name})` 使用 `file_name`（不含路径）过滤，不同目录下的同名文件会导致误删。

**改进方案**: 元数据中同时存储完整路径和文件名，删除时使用完整路径匹配：
```python
# 存储时
metadata = {"source_file": str(file_path), "file_name": file_path.name}

# 删除时
collection.get(where={"source_file": str(full_path)})
```

### 3.3 [中等] chunk_id 格式导致 ID 冲突

**文件**: `thinkvault/core/storage.py`

chunk_id 格式为 `{source_file}_{chunk_index}`，`source_file` 只含文件名，同名文件产生 ID 冲突。

**改进方案**: 使用完整路径的哈希作为前缀：
```python
import hashlib
path_hash = hashlib.md5(str(file_path).encode()).hexdigest()[:8]
chunk_id = f"{path_hash}_{file_path.name}_{chunk_index}"
```

### 3.4 [中等] generate() 与 generate_stream() 重复代码

**文件**: `thinkvault/core/thinkvault_llm.py`

两个方法各自独立构建 headers 和 payload，`max_new_tokens=256` 硬编码默认值出现多次。

**改进方案**: 抽取公共方法：
```python
def _build_payload(self, messages: list, max_tokens: int = 256, 
                    temperature: float = 0.7, **kwargs) -> dict:
    return {
        "model": self._model_name,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        **kwargs
    }
```

### 3.5 [中等] SummaryGenerator._get_doc_raw_text() 全量加载性能问题

**文件**: `thinkvault/core/summary_generator.py` (L123-153)

当 `doc_id` 不匹配 `source_file` 时，调用 `collection.get(include=["metadatas", "documents"])` 获取整个集合再逐条匹配。大型知识库下造成严重内存消耗。

**改进方案**: 使用 ChromaDB 的 where 条件过滤，或维护 source_file → doc_id 的映射表。

### 3.6 [中等] SummaryGenerator 使用 ThreadPoolExecutor + asyncio.run

**文件**: `thinkvault/core/summary_generator.py` (L155-170)

在 FastAPI 异步环境中绕过事件循环，非最佳实践。

**改进方案**: 改为 `asyncio.create_task()` 或将调用方改为异步。

### 3.7 [低] watched_dir_store.py 存在重复函数

`update_enabled()` 与 `set_enabled()` 功能完全相同；`update_last_scan()` 与 `update_scan_time()` 功能完全相同。

**改进方案**: 保留语义更清晰的函数名，删除重复函数。

### 3.8 [低] doc_summary_store.py 中 `update()` 和 `update_summary()` 重复

功能签名和逻辑完全相同。

**改进方案**: 合并为单一方法，用别名保持向后兼容。

### 3.9 [低] 迁移异常被静默吞没

**文件**: `doc_summary_store.py`、`file_change_store.py`、`watched_dir_store.py`

`_run_migrations()` 中所有 `except Exception: pass`，迁移失败无日志。

**改进方案**: 改为 `except Exception as e: logger.warning(f"Migration skipped: {e}")`

### 3.10 [低] launch.py 文档与实际不一致

注释仍提及 llama-cpp-python，但 v2.0 已迁移到 OpenAI 兼容 API。

### 3.11 [低] hardware.py 硬编码 OS 名称

`profile.os_name = f"Windows"` 在所有平台返回 "Windows"。

**改进方案**: 使用 `platform.system()`。

### 3.12 [低] download_qwen25_7b.py 硬编码本地路径

`SAVE_DIR = r"D:\DMX"` 为开发者个人路径，且文件头部标注为 "HybridMind" 而非 ThinkVault。

---

## 4. 安全问题

### 4.1 [严重] API Token 硬编码泄露

**文件**: `scripts/e2e_test.py` (L46)

```python
API_TOKEN = os.environ.get("THINKVAULT_API_TOKEN", "B-tOnoFYbfZf76tb7H0BCfZAy1tddNICnEZNNaqAbSA")
```

Fallback 值直接暴露了 Token。如果该 Token 在生产环境使用，需立即轮换。

**改进方案**:
1. 移除硬编码 fallback，改为 `os.environ.get("THINKVAULT_API_TOKEN")` 或直接抛出异常
2. 轮换所有已泄露的 Token
3. 将 `.env` 加入 `.gitignore`（已做）并确认未被提交到版本历史

### 4.2 [严重] OllamaSetup.exe (1.3GB) 存在于项目目录

该二进制文件不应出现在源码仓库中，可能包含恶意代码且极大增加仓库体积。

**改进方案**:
1. 立即删除 `OllamaSetup.exe`
2. 从 Git 历史中清除（`git filter-branch` 或 `BFG Repo-Cleaner`）
3. 添加 `*.exe` 到 `.gitignore`

### 4.3 [中等] Token 通过 URL Query Parameter 传递

**文件**: `thinkvault/api/server.py`

`?token=xxx` 方式传递 Token 会被浏览器历史、服务器日志、Referer 头记录。

**改进方案**: 短期：使用短期一次性 Token（服务端签发 → 验证 → 作废）。长期：使用支持自定义 header 的 EventSource polyfill（如 `eventsource-polyfill`）。

### 4.4 [中等] Token 明文存储在 localStorage

**文件**: `thinkvault/webui/app.js`

任何 XSS 漏洞都可窃取 Token。

**改进方案**: 使用 HttpOnly Cookie 或 sessionStorage（降低持久性风险）。

### 4.5 [中等] 速率限制基于内存字典

**文件**: `thinkvault/api/server.py`

服务重启后丢失，多 worker 部署时各 worker 限制状态不共享。

**改进方案**: 使用 Redis 或 SQLite 持久化限制状态；或使用滑动窗口算法 + 共享存储。

### 4.6 [低] 路径安全白名单可能被符号链接绕过

**文件**: `thinkvault/core/scanner.py`

Windows 上未检查符号链接，可能被利用访问白名单外的文件。

**改进方案**: 使用 `os.path.realpath()` 解析真实路径后再做白名单检查。

### 4.7 [低] Dockerfile 中未设置非 root 用户

**文件**: `Dockerfile`

容器以 root 用户运行，违反最小权限原则。

**改进方案**:
```dockerfile
RUN useradd -m appuser
USER appuser
```

---

## 5. 前端问题

### 5.1 [严重] 前端 API 端点与后端不匹配

**文件**: `thinkvault/webui/app.js`

`startScan()` 调用 `/api/kb/manage/scan`，需确认是否与 `kb_manage.py` 中的路由一致。项目中同时存在 `/api/documents/scan`（documents.py）和 `/api/kb/manage/scan`（kb_manage.py），前端调用可能指向错误端点。

**改进方案**: 统一扫描 API 端点，消除歧义。建议保留 `/api/kb/manage/scan`（更符合 RESTful 语义），删除 `/api/documents/scan`。

### 5.2 [中等] loadWatchDirs() 函数体为空

**文件**: `thinkvault/webui/app.js`

前端 KB 管理面板中的"监听目录"功能不可用。

**改进方案**: 实现该函数，对接 `GET /api/kb/manage/watch-dirs` 端点。

### 5.3 [中等] 引用 Google Fonts 与"完全离线"定位矛盾

**文件**: `thinkvault/webui/index.html`

离线环境下字体加载失败导致界面异常。

**改进方案**:
1. 将字体文件下载到 `webui/vendor/fonts/` 目录
2. 修改 CSS 中的 `@font-face` 使用本地路径
3. 或使用系统字体栈作为 fallback

### 5.4 [中等] XSS 风险 — innerHTML + CDN 依赖的 DOMPurify

**文件**: `thinkvault/webui/app.js`

离线环境下 DOMPurify CDN 加载失败时，XSS 防护完全失效。

**改进方案**: 将 `dompurify.js` 下载到 `webui/vendor/` 目录，确保离线可用。

### 5.5 [低] CSS 变量引用不存在

**文件**: `thinkvault/webui/style.css`

部分样式引用 `--bg-primary`、`--bg-secondary` 等未定义的 CSS 变量。

**改进方案**: 补充缺失的 CSS 变量定义，或替换为已定义的变量。

### 5.6 [低] 前端错误处理粗糙

多处 `catch (e)` 吞没错误，只显示通用提示。

**改进方案**: 记录详细错误到 console，并区分网络错误、认证错误、业务错误给用户不同提示。

---

## 6. 架构问题

### 6.1 [严重] Store 返回模块而非实例

**文件**: `thinkvault/core/container.py`

`_get_file_change_store()` 等方法返回 Python 模块而非类实例，与容器管理单例的设计模式不一致，导致测试和替换困难。

**改进方案**: 将所有 Store 模块重构为类，统一由 IOC 容器管理：

```python
# 重构前
def _get_file_change_store(self):
    from thinkvault.core import file_change_store
    return file_change_store  # 返回模块

# 重构后
def _get_file_change_store(self):
    return FileChangeStore(self._get_db_path("file_changes"))
```

### 6.2 [严重] 模块级单例与 IOC 容器冲突

**文件**: `doc_summary_store.py`、`file_change_store.py`、`watched_dir_store.py`、`bm25_index_store.py`、`document_store.py`、`conversation_store.py`

这些 Store 使用 `_store = None` + `global _store` + `_get_store()` 的模块级单例模式，绕过了容器的统一管理。

**改进方案**: 逐步迁移到类实例 + IOC 容器管理模式。可分阶段：
1. 第一阶段：保持模块级单例，但通过 Container 的 `_get_xxx_store()` 方法统一访问入口
2. 第二阶段：重构为类，Container 管理生命周期

### 6.3 [中等] 6 个独立 SQLite 数据库文件

| 数据库 | 用途 |
|--------|------|
| `documents.db` | 文档元数据 |
| `conversations.db` | 会话和消息 |
| `doc_summaries.db` | 文档摘要 |
| `file_changes.db` | 文件变更追踪 |
| `watched_dirs.db` | 监控目录配置 |
| `bm25_index.db` | BM25 索引持久化 |

问题：多个连接管理器、独立 WAL 模式配置、无法跨表事务、连接池浪费。

**改进方案**: 合并为单一 `thinkvault.db`，各功能使用不同表前缀（如 `doc_`、`conv_`、`summary_`），统一连接管理器。

### 6.4 [中等] Container 每次创建新的 IncrementalIndexer

**文件**: `thinkvault/core/container.py`

`_create_watchdog_watcher()` 每次调用都创建新实例，违背容器单例原则。

**改进方案**: 在 Container 中缓存 IncrementalIndexer 实例。

### 6.5 [中等] conversation_store 删除操作未使用事务

**文件**: `thinkvault/core/conversation_store.py`

删除会话时先删 messages 再删 conversations，中间步骤失败会留孤儿记录。

**改进方案**:
```python
def delete_conversation(conv_id):
    with db.connect() as conn:
        conn.execute("BEGIN")
        try:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
            conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            conn.execute("COMMIT")
        except:
            conn.execute("ROLLBACK")
            raise
```

### 6.6 [低] db.py 连接锁粒度过粗

锁覆盖了整个操作（包括读），高并发读场景下成为瓶颈。

**改进方案**: 改为读写锁（`threading.RLock` 用于写，读无锁）或使用 `sqlite3` 的 WAL 模式 + 适当隔离级别。

### 6.7 [低] 每次启动都尝试所有 ALTER TABLE 迁移

**改进方案**: 维护 `schema_version` 表，按版本号执行增量迁移。

---

## 7. 测试覆盖问题

### 7.1 [严重] API 路由集成测试覆盖率严重不足

| 未测试模块 | 说明 |
|-----------|------|
| `kb_manage.py` | 知识库管理路由，0% 覆盖 |
| `incremental_indexer.py` | 增量索引器，0% 覆盖 |
| `summary_generator.py` | 摘要生成器，0% 覆盖 |
| `watchdog_watcher.py` | 文件监控，0% 覆盖 |
| `bm25_index_store.py` | BM25 索引持久化，0% 覆盖 |
| `doc_summary_store.py` | 文档摘要存储，0% 覆盖 |
| `file_change_store.py` | 文件变更存储，0% 覆盖 |
| `watched_dir_store.py` | 监控目录存储，0% 覆盖 |

现有测试文件中 `test_v2.py` 已标记 skip，`test_api_integration.py` 和 `test_e2e_mock.py` 使用 Mock 而非真实集成。

**改进方案**:
1. 建立测试基础设施：pytest 配置、fixtures、测试数据库隔离
2. 按优先级补充测试：Store 模块 → API 路由 → 增量索引 → 集成测试
3. 引入覆盖率目标：核心模块 ≥ 80%，API 路由 ≥ 60%

### 7.2 [中等] 测试目录不规范

测试文件位于 `test/` 而非标准 `tests/`，pyproject.toml 中无 pytest 配置，无覆盖率配置。

**改进方案**:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]

[tool.coverage.run]
source = ["thinkvault"]
omit = ["test/*", "tests/*"]
```

### 7.3 [中等] 无 CI/CD 配置

**改进方案**: 添加 GitHub Actions 配置：
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install -e ".[dev]"
      - run: pytest --cov=thinkvault
```

---

## 8. 功能完整性问题

### 8.1 [中等] 大文件上传全量读入内存

**文件**: `thinkvault/api/routes/documents.py`

`content = await file.read()` 对大文件（如 500MB PDF）可能导致 OOM。

**改进方案**: 使用流式写入临时文件：
```python
import tempfile, shutil
with tempfile.NamedTemporaryFile(delete=False, suffix=file.filename) as tmp:
    shutil.copyfileobj(file.file, tmp)
    tmp_path = tmp.name
```

### 8.2 [中等] WhisperModel 每次调用重新加载

**文件**: `thinkvault/core/parser.py`

加载时间可达数十秒，严重影响用户体验。

**改进方案**: 在 Container 中维护 WhisperModel 单例，惰性加载。

### 8.3 [中等] BM25 索引文件名直接使用知识库名

**文件**: `thinkvault/core/bm25_index_store.py`

虽然有正则校验，但不够安全。

**改进方案**: 使用知识库 ID 或名称的哈希作为文件名。

### 8.4 [低] `_DEFAULT_INTENT_KEYWORDS` 过于宽泛

**文件**: `thinkvault/core/retriever.py`

"什么"、"如何"等极常见词导致几乎所有输入都触发检索，意图判断形同虚设。

**改进方案**: 引入二级判断——关键词匹配后，再通过语义相似度阈值确认是否真正需要检索。

### 8.5 [低] 会话标题更新逻辑不合理

**文件**: `thinkvault/api/routes/chat.py`

`conv["title"] == _make_title(req.message)` 判断条件几乎不成立。

**改进方案**: 改为首次消息时设置标题，或使用 LLM 生成标题。

### 8.6 [低] `_model_load_progress` 全局字典不支持多 worker

**文件**: `thinkvault/api/routes/model.py`

**改进方案**: 使用共享存储（Redis/SQLite）或只在单 worker 场景下使用。

---

## 9. 文档与注释问题

### 9.1 [中等] README 项目结构与实际代码不一致

README 列出的文件名与实际不符：缺少 `kb_manage.py`、`incremental_indexer.py`、`summary_generator.py`、`watchdog_watcher.py` 等新文件。

**改进方案**: 更新 README 中的项目结构树，保持与代码同步。

### 9.2 [中等] CHANGELOG 头部含 AIGC 噪声

文件头部包含与项目无关的 AI 生成元数据/水印，应清理。

### 9.3 [中等] 默认嵌入模型名不一致

README 中说 `all-MiniLM-L6-v2`，代码默认为 `BAAI/bge-small-zh-v1.5`。

**改进方案**: 统一为 `BAAI/bge-small-zh-v1.5`（中文场景更适合），更新 README。

### 9.4 [中等] pyproject.toml keywords 仍包含 llama-cpp-python

**改进方案**: 移除 `llama-cpp-python`，替换为 `openai-compatible-api`。

### 9.5 [低] 缺少 `.env.example`

**改进方案**:
```bash
# .env.example
THINKVAULT_API_TOKEN=your-secure-token-here
THINKVAULT_LLM_BASE_URL=http://localhost:8080/v1
THINKVAULT_LLM_MODEL=qwen2.5-7b-instruct
THINKVAULT_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
THINKVAULT_SCAN_DIRS=/path/to/your/documents
```

### 9.6 [低] 缺少独立 API 文档

**改进方案**: 补充 SSE 流式接口、扫描 API、知识库管理 API 的使用说明。

---

## 10. 依赖与构建问题

### 10.1 [严重] torch 作为核心依赖过于重量级

`torch>=2.0.0,<3.0.0` 安装包约 2GB，实际仅用于 GPU 检测和嵌入加速。

**改进方案**:
```toml
[project]
dependencies = [
    # ... 其他依赖，不含 torch
]

[project.optional-dependencies]
gpu = ["torch>=2.0.0,<3.0.0"]
full = ["torch>=2.0.0,<3.0.0", "faster-whisper", "ffmpeg-python"]
```

安装命令从 `pip install thinkvault` 变为 `pip install thinkvault[gpu]`。

### 10.2 [中等] `.gitignore` 不完整

缺少对 `.coverage`、`*.exe`、`build/`、`dist/`、`*.egg-info/`、`demo_docs/`、`temp_uploads/` 的忽略规则。

**改进方案**: 补充以下规则：
```gitignore
# Build artifacts
build/
dist/
*.egg-info/

# Coverage
.coverage
htmlcov/

# Binaries
*.exe

# Temp
demo_docs/
temp_uploads/
```

### 10.3 [低] Dockerfile 中额外安装 python-pptx 和 openpyxl

如果 `requirements.txt` 已包含这些包则重复安装；如果未包含则 requirements.txt 不完整。

**改进方案**: 确认 requirements.txt 完整性，删除 Dockerfile 中的重复安装。

---

## 11. 优先修复路线图

### P0 — 阻断性（1-2 天）

| # | 问题 | 影响 | 工作量 |
|---|------|------|--------|
| 1 | 修复同名文件误删（使用完整路径替代文件名） | 数据丢失风险 | 2h |
| 2 | 轮换 API Token 并移除硬编码 fallback | 安全泄露 | 30min |
| 3 | 删除 OllamaSetup.exe 并清理 Git 历史 | 仓库污染 + 安全 | 1h |
| 4 | 修复前端 API 端点不匹配 | 功能不可用 | 1h |
| 5 | 将 Google Fonts/DOMPurify 等前端 CDN 依赖本地化 | 离线环境不可用 | 1h |

### P1 — 重要（1 周）

| # | 问题 | 影响 | 工作量 |
|---|------|------|--------|
| 6 | torch 改为可选依赖 | 安装门槛过高 | 2h |
| 7 | 统一 Store 模式（模块级单例 → 类实例 + IOC） | 架构债务 | 1d |
| 8 | 合并 6 个 SQLite 数据库为单一数据库 | 事务一致性 + 连接管理 | 1d |
| 9 | 补充核心模块单元测试（Store、API 路由） | 质量保障 | 2d |
| 10 | 修复 URL 路径拼接 + 重复代码（thinkvault_llm.py） | 可维护性 | 2h |
| 11 | 大文件上传改为流式写入 | OOM 风险 | 2h |
| 12 | WhisperModel 改为单例 | 性能 | 1h |
| 13 | conversation_store 删除使用事务 | 数据一致性 | 30min |
| 14 | 完善 .gitignore + 清理构建产物 | 仓库清洁 | 1h |
| 15 | 更新 README/CHANGELOG/文档一致性 | 用户误导 | 2h |

### P2 — 改进（持续迭代）

| # | 问题 | 影响 | 工作量 |
|---|------|------|--------|
| 16 | Token 传递方案优化（短期一次性 Token） | 安全增强 | 4h |
| 17 | 速率限制持久化（Redis/SQLite） | 多 worker 支持 | 4h |
| 18 | 添加 CI/CD 配置 | 自动化质量保障 | 2h |
| 19 | 补充集成测试和端到端测试 | 质量保障 | 3d |
| 20 | 意图判断优化（二级语义判断） | 检索精度 | 4h |
| 21 | 会话标题生成优化 | 用户体验 | 2h |
| 22 | Dockerfile 非 root 用户 | 安全合规 | 30min |
| 23 | 路径安全 — 符号链接检查 | 安全增强 | 1h |
| 24 | 迁移版本管理（schema_version 表） | 启动性能 | 2h |
| 25 | 添加 .env.example 和独立 API 文档 | 可用性 | 2h |

---

## 12. 附录：完整问题清单

### 按严重程度排序

#### 严重（9 项）

| ID | 类别 | 问题摘要 | 文件 |
|----|------|---------|------|
| CQ-01 | 代码质量 | URL 路径拼接 Bug | `thinkvault_llm.py` |
| CQ-02 | 代码质量 | 同名文件误删向量数据 | `incremental_indexer.py`, `documents.py` |
| SEC-01 | 安全 | API Token 硬编码泄露 | `e2e_test.py` |
| SEC-02 | 安全 | OllamaSetup.exe 存在于项目 | 项目根目录 |
| FE-01 | 前端 | API 端点与后端不匹配 | `app.js` |
| ARCH-01 | 架构 | Store 返回模块而非实例 | `container.py` |
| ARCH-02 | 架构 | 模块级单例与 IOC 容器冲突 | 多个 Store 文件 |
| TEST-01 | 测试 | API 路由集成测试覆盖率 0% | `test/` |
| DEP-01 | 依赖 | torch 作为核心依赖 | `pyproject.toml` |

#### 中等（23 项）

| ID | 类别 | 问题摘要 | 文件 |
|----|------|---------|------|
| CQ-03 | 代码质量 | chunk_id 格式 ID 冲突 | `storage.py` |
| CQ-04 | 代码质量 | generate/stream 重复代码 | `thinkvault_llm.py` |
| CQ-05 | 代码质量 | SummaryGenerator 全量加载性能 | `summary_generator.py` |
| CQ-06 | 代码质量 | ThreadPoolExecutor + asyncio.run | `summary_generator.py` |
| SEC-03 | 安全 | Token 通过 URL Query 传递 | `server.py` |
| SEC-04 | 安全 | Token 明文存储在 localStorage | `app.js` |
| SEC-05 | 安全 | 速率限制基于内存字典 | `server.py` |
| FE-02 | 前端 | loadWatchDirs() 函数体为空 | `app.js` |
| FE-03 | 前端 | Google Fonts 与离线定位矛盾 | `index.html` |
| FE-04 | 前端 | innerHTML + CDN DOMPurify XSS 风险 | `app.js` |
| ARCH-03 | 架构 | 6 个独立 SQLite 数据库 | 多个 Store 文件 |
| ARCH-04 | 架构 | Container 每次创建新 IncrementalIndexer | `container.py` |
| ARCH-05 | 架构 | conversation_store 删除无事务 | `conversation_store.py` |
| TEST-02 | 测试 | 测试目录不规范 | `test/` |
| TEST-03 | 测试 | 无 CI/CD 配置 | 项目根目录 |
| FUNC-01 | 功能 | 大文件上传全量读入内存 | `documents.py` |
| FUNC-02 | 功能 | WhisperModel 每次重新加载 | `parser.py` |
| FUNC-03 | 功能 | BM25 索引文件名使用知识库名 | `bm25_index_store.py` |
| DOC-01 | 文档 | README 项目结构与实际不一致 | `README.md` |
| DOC-02 | 文档 | CHANGELOG 头部含 AIGC 噪声 | `CHANGELOG.md` |
| DOC-03 | 文档 | 默认嵌入模型名不一致 | `README.md` vs `embedder.py` |
| DOC-04 | 文档 | keywords 仍含 llama-cpp-python | `pyproject.toml` |
| DEP-02 | 依赖 | .gitignore 不完整 | `.gitignore` |

#### 低（18 项）

| ID | 类别 | 问题摘要 | 文件 |
|----|------|---------|------|
| CQ-07 | 代码质量 | watched_dir_store 重复函数 | `watched_dir_store.py` |
| CQ-08 | 代码质量 | doc_summary_store 重复函数 | `doc_summary_store.py` |
| CQ-09 | 代码质量 | 迁移异常静默吞没 | 多个 Store 文件 |
| CQ-10 | 代码质量 | launch.py 文档过时 | `launch.py` |
| CQ-11 | 代码质量 | hardware.py 硬编码 OS 名称 | `hardware.py` |
| CQ-12 | 代码质量 | download_qwen25_7b.py 硬编码路径 | `scripts/` |
| SEC-06 | 安全 | 符号链接绕过路径白名单 | `scanner.py` |
| SEC-07 | 安全 | Dockerfile 未设置非 root 用户 | `Dockerfile` |
| FE-05 | 前端 | CSS 变量引用不存在 | `style.css` |
| FE-06 | 前端 | 错误处理粗糙 | `app.js` |
| ARCH-06 | 架构 | db.py 连接锁粒度过粗 | `db.py` |
| ARCH-07 | 架构 | 每次启动执行所有迁移 | 多个 Store 文件 |
| FUNC-04 | 功能 | 意图关键词过于宽泛 | `retriever.py` |
| FUNC-05 | 功能 | 会话标题更新逻辑不合理 | `chat.py` |
| FUNC-06 | 功能 | model_load_progress 不支持多 worker | `model.py` |
| DOC-05 | 文档 | 缺少 .env.example | 项目根目录 |
| DOC-06 | 文档 | 缺少独立 API 文档 | 项目根目录 |
| DEP-03 | 依赖 | Dockerfile 重复安装依赖 | `Dockerfile` |

---

> **文档结束**  
> 本文档基于 2026-06-08 项目代码快照生成，建议修复后重新审计并更新本文档。
