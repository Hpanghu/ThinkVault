# ThinkVault 项目记忆

## 项目概述
- **类型**: Python FastAPI + 原生 HTML/CSS/JS RAG 系统
- **路径**: D:\ThinkVault
- **前端**: `thinkvault/webui/` (index.html, style.css, app.js + vendor/)
- **后端**: FastAPI on port 8000, serves static webui via `StaticFiles`
- **核心**: LLM 推理通过 httpx 调用 OpenAI 兼容 API（llama-cpp-python server），嵌入模型 sentence-transformers，BM25+Vector 混合 RAG

## 技术架构
- **版本**: v2.0.0 — GGUF → OpenAI API 迁移完成
- **核心模块** (thinkvault/core/): container.py, thinkvault_llm.py, retriever.py, parser.py, chunker.py, embedder.py, storage.py, document_store.py, conversation_store.py, scanner.py, db.py
- **API 路由** (thinkvault/api/routes/): chat.py, conversations.py, documents.py, kb.py, kb_manage.py, model.py
- **前端**: 单页 WebUI，Geist + JetBrains Mono 字体，Emerald (#10b981) 主题，馆长/图书管理员隐喻
- **依赖**: FastAPI, httpx, chromadb, sentence-transformers, rank-bm25, torch, pymupdf, python-docx

## 设计决策
- 2026-06-01: v2.0.0 GGUF → OpenAI API 迁移完成
- 全部中文 UI，"知识馆长" 品牌定位
- 反幻觉机制：系统提示词约束 + 空检索结果固定回复
- 检索降级：后端不可用时返回固定提示
- 意图判断：两级（关键词 + 语义相似度锚点）
- IOC 容器：Container 统一管理单例，惰性加载
- API Token 认证：Bearer header + ?token= 查询参数（SSE 兼容）
- 速率限制：内存滑动窗口（IP 维度）
- 2026-06-05: 性能优化 — 环境变量控制 Rerank/TopK/分层阈值，摘要嵌入预计算，智能检索入口
- 2026-06-06: BM25 索引持久化 — 冷启动从 18-53s 降到 1-3s，三级缓存（内存→磁盘→全量重建）
- 2026-06-07: Ollama → llama-cpp-python server 迁移 — 删除所有 Ollama 特定逻辑，端口 11434→8080，新增模型下载脚本 scripts/download_model.py

## 已知问题（来自 CHANGELOG + 审计报告）
1. API routes 无集成测试（0% 覆盖）
2. parser.py 覆盖率 46%
3. Docker 环境未验证
4. PyPI twine check 未完成
5. 集成测试存在失败项
6. **2026-06-08 全面审计**: 50 个问题（严重 9 / 中等 23 / 低 18），详见 `docs/IMPROVEMENT_PLAN.md`
   - P0 阻断性：同名文件误删、Token 硬编码泄露、前端 API 端点不匹配、CDN 依赖与离线矛盾
   - P1 重要：torch 改可选依赖、统一 Store 模式、合并 SQLite 数据库、补充测试
   - P2 改进：Token 传递优化、CI/CD、意图判断优化

## 核心模块扩展（v2.0+ 新增）
- **thinkvault/core/**: incremental_indexer.py, summary_generator.py, watchdog_watcher.py, bm25_index_store.py, doc_summary_store.py, file_change_store.py, watched_dir_store.py
- **thinkvault/api/routes/**: kb_manage.py (新增)
- **问题**: 6 个独立 SQLite 数据库文件，模块级单例与 IOC 容器冲突

## 需求路线图（意向.txt）
- MVP: 本地聊天 + 拖入文档提问 ✅
- V1.0: 知识库管理 + 混合检索 + 多格式 🔄
- V2.0: 智能知识管理 + Agent 自动化 ⏳

## 运行环境
- Python venv: `C:/Users/Hi/.workbuddy/binaries/python/envs/thinkvault/`
- 启动: `python -m thinkvault.launch` (port 8000)
- LLM 后端: `python -m llama_cpp.server --model ~/.thinkvault/models/xxx.gguf --port 8080`
- API Token: `THINKVAULT_API_TOKEN=B-tOnoFYbfZf76tb7H0BCfZAy1tddNICnEZNNaqAbSA`

## 2026-06-08 整体评估（更新）
- 代码质量：B-，架构清晰但债务累积（Store 模式不一致、重复代码、6 个独立 SQLite）
- 测试覆盖：单元 162/162 通过，但 8 个核心模块 0% 覆盖，API 集成测试缺失
- 前端：馆长隐喻完成，但存在 API 端点不匹配、CDN 依赖与离线矛盾
- 安全：Token 硬编码泄露、OllamaSetup.exe 残留、localStorage 明文存 Token
- 文档：README 与代码不同步、嵌入模型名不一致、缺 .env.example
- 改进文档：`D:\ThinkVault\docs\IMPROVEMENT_PLAN.md`
