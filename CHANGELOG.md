# Changelog

## v2.0.0 (2026-06-22)

### 架构重构
- API 路由拆分为独立模块（chat / conversations / documents / kb / kb_manage / model / services）
- Retriever 分解为 Mixin 架构（`_BM25Mixin` / `_IntentMixin` / `_ContextMixin`）
- Store 模块提取 `BaseStore` 基类，消除重复初始化代码
- 新增 `indexer.py` 统一文档索引入口
- Pydantic v2 响应模型，OpenAPI 文档自动生成

### 性能优化
- BM25 引擎优先使用 `bm25s`（C 扩展，10-50x 加速），安装失败时自动回退到 `rank_bm25`
- 向量检索 + BM25 并行执行（`ThreadPoolExecutor`）
- BM25 索引 gzip 持久化，冷启动从 13s 降至 1-3s
- ONNX Runtime 三后端架构（ONNX → PyTorch → API）
- Embedding 查询缓存（LRU + TTL），避免重复向量化
- SQLite 连接池优化，高并发场景性能提升

### 安全加固
- SSRF/DNS rebinding 防护（IP 验证 + 云元数据地址拦截 + RFC1918 网段过滤）
- XSS 修复（`escAttr()` 属性转义）
- Docker 非 root 用户运行
- 安全响应头（X-Content-Type-Options / X-Frame-Options / Referrer-Policy）
- 速率限制中间件（滑动窗口算法）
- 输入验证增强（文件类型白名单、文件大小限制、文件名长度限制）

### 稳定性修复
- `threading.Lock` → `RLock`，修复容器工厂函数嵌套调用死锁
- 数据库连接泄漏修复（`try/finally` 确保关闭）
- 服务管理器文件句柄泄漏修复
- 大文件保护（100MB 限制）
- SSE 流式 JSON 解析错误不中断流（跳过损坏行）

### 新增功能
- 知识库高级管理 API（增量扫描 / 文件夹监听 / 文档摘要 / 后台任务）
- 一键启动推理服务（自动发现 GGUF 模型 → 启动 llama-cpp-python → 连接后端）
- 分页查询（文档列表 / 会话列表）
- 异步文档上传（`asyncio.to_thread`）
- 文件夹实时监听（watchdog）
- 文档摘要生成（summary_generator）
- 后台任务队列（task_manager）
- 硬件检测 API（CPU/RAM/GPU/推荐档位）

### 推理后端支持
- 从 llama-cpp-python（GGUF 本地加载）迁移到 httpx OpenAI 兼容 API 调用
- 支持所有 OpenAI 兼容后端（Ollama、vLLM、LM Studio、OpenAI 等）

### 文档格式支持
- PDF（PyMuPDF）
- DOCX（python-docx）
- PPTX（python-pptx，可选）
- XLSX（openpyxl，可选）
- TXT、Markdown（内置）
- MP3/MP4（faster-whisper，可选）
- OCR 扫描件识别（rapidocr-onnxruntime，可选）

### 测试覆盖
| 模块 | 覆盖率 | 说明 |
|------|--------|------|
| retriever.py | 98% | 混合检索全路径覆盖 |
| thinkvault_llm.py | 83% | 流式/非流式/降级路径覆盖 |
| chunker.py | 85% | 分块策略覆盖 |
| document_store.py | 100% | 文档存储完整覆盖 |
| db.py | 100% | 数据库完整覆盖 |
| embedder.py | 80%+ | 向量化引擎覆盖 |
| **单元测试** | **162 / 162 全通过** | |

### 部署方式
- Dockerfile + docker-compose.yml 一键部署
- PyInstaller 打包（Windows 单文件 .exe）
- GitHub Actions CI/CD（pytest + mypy + flake8 + black）

---

## v1.0.0 (2026-05-01)

### 初始版本
- 基础 RAG 流水线（文档解析 → 分块 → 向量化 → 检索 → 生成）
- PDF / DOCX / TXT 文档支持
- BM25 + 向量混合检索
- SSE 流式对话
- Web UI
- SQLite 数据持久化
