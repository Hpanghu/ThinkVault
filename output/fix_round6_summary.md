# ThinkVault 审计问题修复总结 — Round 6

**修复日期**：2026-05-31  
**审计来源**：audit_check.md（21 个问题）  
**修复范围**：全部 21 个问题（1 严重 / 6 高 / 11 中 / 3 低）

---

## 修复状态总览

| 编号 | 维度 | 严重度 | 问题简述 | 状态 |
|------|------|:------:|----------|:----:|
| S01 | 安全 | 严重 | XSS 防护回退方案存在绕过窗口 | ✅ |
| S02 | 安全 | 高 | CDN 依赖无完整性校验 | ✅ |
| S03 | 安全 | 高 | API 端点无认证/授权机制 | ✅ |
| S04 | 安全 | 中 | CORS 配置过于宽松 | ✅ |
| CQ01 | 代码质量 | 高 | total_changes 误判删除结果 | ✅ |
| CQ02 | 代码质量 | 中 | _recursive_split 偏移量漂移 | ✅ |
| CQ03 | 代码质量 | 中 | ChunkConfig.validate() 静默修改 | ✅ |
| CQ04 | 代码质量 | 中 | _make_title Unicode 边界空字符串 | ✅ |
| CQ05 | 代码质量 | 低 | 版本字符串混乱 | ✅ |
| AR01 | 架构 | 高 | 模块级单例导致测试隔离困难 | ✅ |
| AR02 | 架构 | 中 | Embedder 缓存目录依赖开发目录结构 | ✅ |
| AR03 | 架构 | 中 | launch.py 硬编码测试路径 | ✅ |
| AR04 | 架构 | 低 | UUID 截断降低标识符熵值 | ✅ |
| PF01 | 性能 | 中 | 向量清理时全量加载 ID 列表 | ✅ |
| PF02 | 性能 | 中 | 所有查询均执行检索（无语义路由） | ✅ |
| PF03 | 性能 | 低 | DOCX 锁等待时间可配置化 | ✅ |
| DP01 | 依赖 | 高 | torch 版本未约束 | ✅ |
| DP02 | 依赖 | 高 | gguf-chat 包可用性未验证 | ✅ |
| DP03 | 依赖 | 中 | requirements.txt 与 pyproject.toml 不一致 | ✅ |
| TS01 | 测试 | 中 | 集成测试引用错误项目路径 | ✅ |
| TS02 | 测试 | 中 | format_context 测试断言不精确 | ✅ |

---

## 逐项修复详情

### S01 [严重] XSS 防护回退方案 — `app.js`

**修改文件**：`thinkvault/webui/app.js`

- 移除不完整的正则 `sanitize()` 函数（无法防护 SVG/MathML/data: 等攻击面）
- `renderMarkdown()` 中 DOMPurify 不可用时，回退到 `textContent` 赋值（纯文本渲染），杜绝 XSS 绕过

---

### S02 [高] CDN SRI / 本地化 — `index.html`

**修改文件**：`thinkvault/webui/index.html`  
**新增文件**：`thinkvault/webui/vendor/marked.min.js`、`thinkvault/webui/vendor/purify.min.js`

- 将 marked 和 DOMPurify 从 jsdelivr CDN 下载到本地 `vendor/` 目录
- script 标签改为引用本地文件，彻底消除 CDN 劫持风险

---

### S03 [高] API 认证 — `server.py` + `routes/`

**修改文件**：`thinkvault/api/server.py`、`thinkvault/api/routes/__init__.py`

- 新增 `verify_api_token` FastAPI 依赖注入
- 通过环境变量 `THINKVAULT_API_TOKEN` 控制：未设置则跳过（开发兼容），设置后要求 `Authorization: Bearer <token>`
- 全局路由注入认证依赖，`/api/health` 端点豁免（`dependencies=[]`）

---

### S04 [中] CORS 配置 — `server.py`

**修改文件**：`thinkvault/api/server.py`

- CORS origins 默认值明确限定为 `http://127.0.0.1:8000,http://localhost:8000`
- 注释更新为生产环境部署指引

---

### CQ01 [高] `total_changes` 误判 — `conversation_store.py`

**修改文件**：`thinkvault/core/conversation_store.py`

- `update_conversation()` 中 `conn.total_changes > 0` → `cursor.rowcount > 0`
- `total_changes` 是连接生命周期累计值，多次操作下会误判；`cursor.rowcount` 反映当前语句影响行数

---

### CQ02 [中] 偏移量漂移 — `chunker.py`

**修改文件**：`thinkvault/core/chunker.py`

- `_recursive_split()` 中：空 `part_with_sep` 虽然不生成 chunk，但 `current_offset` 现在正确推进，保持后续 chunk 偏移量准确

---

### CQ03 [中] `validate()` 静默修改 — `chunker.py`

**修改文件**：`thinkvault/core/chunker.py`

- `ChunkConfig.validate()` 中 `chunk_overlap >= chunk_size` 时改为抛出 `ValueError`，而非静默赋值为 `chunk_size // 4`

---

### CQ04 [中] `_make_title` 边界保护 — `routes/__init__.py`

**修改文件**：`thinkvault/api/routes/__init__.py`

- 添加 `if not result.strip(): return "Chat"` 兜底，防止全部由组合标记组成的消息导致空标题

---

### CQ05 [低] 版本号统一 — `pyproject.toml`

**修改文件**：`pyproject.toml`

- `version` 从 `0.1.0` 更新为 `2.0.0`，与 `server.py` 日志输出和 `__init__.py` 保持一致

---

### AR01 [高] 模块级单例 — `document_store.py` + `conversation_store.py`

**修改文件**：`thinkvault/core/document_store.py`、`thinkvault/core/conversation_store.py`

- `_store = SqliteStore(...)` 模块级立即初始化 → 惰性 `_get_store()` 工厂函数
- 避免 `import` 时立即创建数据库连接，改善测试隔离和启动速度
- 所有函数内部 `_store.connect()` → `_get_store().connect()`

---

### AR02 [中] Embedder 缓存目录 — `embedder.py`

**修改文件**：`thinkvault/core/embedder.py`

- 缓存目录优先级：环境变量 `THINKVAULT_MODEL_DIR` → `appdirs.user_cache_dir("thinkvault")` → 兜底项目 `test/models`
- 兼容 `pip install` 部署后不再处于开发目录的场景

---

### AR03 [中] launch.py 硬编码路径 — `launch.py`

**修改文件**：`thinkvault/launch.py`

- 新增 `_get_model_path()`：优先 `THINKVAULT_DEFAULT_MODEL` 环境变量，其次搜索项目目录候选路径
- 添加 `import os`

---

### AR04 [低] UUID 截断 — `document_store.py` + `conversation_store.py`

**修改文件**：`thinkvault/core/document_store.py`、`thinkvault/core/conversation_store.py`

- `uuid.uuid4().hex[:12]`（48-bit）→ `uuid.uuid4().hex[:16]`（64-bit）
- 百亿级记录场景下碰撞概率降至可忽略

---

### PF01 [中] 向量清理优化 — `routes/__init__.py`

**修改文件**：`thinkvault/api/routes/__init__.py`

- 删除文档时：`collection.get()["ids"]` 全量加载 → `collection.delete(where={"source_file": file_name})` 精确删除
- 避免大知识库 OOM / 超时

---

### PF02 [中] 语义路由 — `routes/__init__.py`

**修改文件**：`thinkvault/api/routes/__init__.py`

- 新增 `_RETRIEVAL_KEYWORDS` 关键词列表和 `_should_retrieve()` 函数
- 仅当问题涉及文档/文件/搜索等关键词时才触发向量检索
- 简单问候（"你好"）不再浪费计算资源

---

### PF03 [低] DOCX 锁等待 — `parser.py`

**修改文件**：`thinkvault/core/parser.py`

- 新增 `DOCX_LOCK_TIMEOUT` 常量，通过 `THINKVAULT_DOCX_TIMEOUT` 环境变量控制（默认 5 秒）
- `_parse_docx()` 添加超时重试循环：文件被占用时每隔 0.5 秒重试
- 新增 `import os, time`

---

### DP01 [高] torch 版本约束 — `requirements.txt`

**修改文件**：`requirements.txt`

- `torch>=2.0.0` → `torch>=2.0.0,<3.0.0`，防止未来大版本不兼容

---

### DP02 [高] gguf-chat 来源说明 — `requirements.txt`

**修改文件**：`requirements.txt`

- 添加注释说明 `gguf-chat` 为本地依赖包，需从项目仓库获取
- 行尾标注 `# 非 PyPI 包，见上方说明`

---

### DP03 [中] 依赖清单一致性 — `requirements.txt`

**修改文件**：`requirements.txt`（与 `pyproject.toml` 同步验证）

- 两个文件现已包含相同的依赖集（torch、gguf-chat 等均已对齐）
- `pyproject.toml` 为唯一真相来源，`requirements.txt` 提供安装指引

---

### TS01 [中] 测试路径修正 — `test_v2.py` + `test_e2e.py`

**修改文件**：`test/test_v2.py`、`test/test_e2e.py`

- `test_v2.py:187`：`F:/AAone/test/...` → `Path(__file__).parent / "test_doc_deep_learning.txt"`
- `test_e2e.py:20`：`F:\AAone\test\models\...` → `Path(__file__).parent.parent / "test" / "models" / ...`

---

### TS02 [中] 测试断言修正 — `test_retriever.py`

**修改文件**：`test/test_retriever.py`

- 断言从 `len(sources) <= 1` → `len(sources) == 1`
- 注释更新为准确描述当前行为：首个超限 chunk 被截断放入（非跳过）

---

## 风险评估

| 风险项 | 说明 |
|--------|------|
| UUID 长度变更 | `[:12]` → `[:16]` 是破坏性变更，新记录 ID 变长 4 字符，但与旧记录兼容（代码不校验 ID 长度） |
| API 认证 | 默认不启用（`THINKVAULT_API_TOKEN` 未设置），零影响；生产部署时设置环境变量即生效 |
| 惰性单例 | 向后兼容，外部调用方式不变；首次访问延迟到首个 API 请求 |

---

*修复工具：edit_file + python_executor + shell_executor*  
*报告生成时间：2026-05-31*
