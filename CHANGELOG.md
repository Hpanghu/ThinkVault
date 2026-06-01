# Changelog

## v2.0.0 (2026-06-01)

### Breaking Changes — GGUF → OpenAI API Migration
- **核心推理引擎**：从 llama-cpp-python（GGUF 本地加载）迁移到 httpx OpenAI 兼容 API 调用
- 移除 llama-cpp-python 依赖，改为 httpx + 标准 OpenAI Chat Completions 协议
- 支持所有 OpenAI 兼容后端（Ollama、vLLM、LM Studio、OpenAI 等）

### Features
- **SSE 流式响应**：实现 Server-Sent Events 流式推理，支持逐 token 输出
- **混合检索**：向量检索 + BM25 关键词检索 + Cross-encoder 重排序三级混合检索
- **意图判断**：两级（关键词 + 语义）意图防御，减少无关问题误入检索
- **Docker 支持**：Dockerfile + docker-compose.yml 一键部署
- **PyInstaller 打包**：Windows 单文件 .exe 打包（~63MB）
- **GitHub Actions CI/CD**：PR 自动运行 pytest + ruff lint，Python 3.10/3.11/3.12 矩阵
- **Ollama 模型固化**：Modelfile + download 脚本纳入仓库

### Bug Fixes
- **B16 修复**：Dockerfile 中 OpenBLAS 符号冲突导致需要 `LD_PRELOAD`
- SSE 流式 JSON 解析错误不中断流（跳过损坏行）
- Cross-encoder 重排序异常时降级而非崩溃
- `close()` 在已关闭 client 上调用不抛异常
- `top_k=0` 时不再传递无效参数
- `generate_async`/`generate_stream_async` 兼容接口修正
- 意图判断中 `embedder.is_loaded` 检查回退

### Test Coverage
| 模块 | 覆盖率 | 说明 |
|---|---|---|
| retriever.py | 98% | 混合检索全路径覆盖 |
| thinkvault_llm.py | 83% | 流式/非流式/降级路径覆盖 |
| chunker.py | 85% | 分块策略覆盖 |
| document_store.py | 100% | 文档存储完整覆盖 |
| db.py | 100% | 数据库完整覆盖 |
| schemas | 100% | API schemas 完整覆盖 |
| **单元测试** | **162 / 162 全通过** | |

### Known Issues
- API routes (chat/documents/conversations/kb/model) 无集成测试覆盖 (0%)
- parser.py 覆盖率 46%，多数格式转换分支未覆盖
- Docker 环境不可用，Docker build 验证未执行
- PyPI twine check 因网络/环境限制未完成

### Tasks for Next Release
- 补充 API routes 集成测试
- parser.py 覆盖率提升至 60%+
- CI 添加 integration test job
- 补充 docker build 验证到 CI