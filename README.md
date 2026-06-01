# ThinkVault

个人 AI 工作台 —— 把本地文档变成可对话的私人图书馆。

ThinkVault 是一款运行在本地的 RAG（检索增强生成）知识库系统，支持 PDF、TXT、DOCX 等多种文档格式，基于 Llama 模型实现本地推理，无需联网即可与你的文档进行智能对话。

## 核心特性

- **全本地运行** — 通过 OpenAI 兼容 API 对接 Ollama 等本地推理后端，数据完全本地化，隐私无忧
- **多格式文档解析** — 支持 PDF、TXT、DOCX 格式，可选 OCR / PPT / Excel 扩展
- **智能分块与向量检索** — 固定窗口 + 重叠分块，BM25 + 向量混合检索
- **SSE 流式对话** — 逐 Token 流式输出，支持多会话管理和对话持久化
- **简洁 Web UI** — 内置单页前端，即开即用

## 系统要求

- Python 3.10+
- 内存：8GB+（推荐 16GB）
- 存储：至少 2GB 用于模型文件

## 安装

### 1. 克隆项目

```bash
git clone https://github.com/yourname/thinkvault.git
cd thinkvault
```

### 2. 安装 Ollama（推理后端）

ThinkVault 使用 OpenAI 兼容 API 模式，默认后端为 Ollama。

```bash
# Windows: 从 https://ollama.com/download 下载安装
# macOS / Linux:
curl -fsSL https://ollama.com/install.sh | sh
```

安装完成后拉取模型：

```bash
ollama pull llama3.2:1b
```

### 3. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

可选扩展：

```bash
# OCR 支持（文档扫描件识别）
pip install paddleocr rapidocr-onnxruntime

# PPT / Excel 文档支持
pip install python-pptx openpyxl

# GPU 加速（需 CUDA 12.1+）
pip install torch>=2.0.0+cu121 --index-url https://download.pytorch.org/whl/cu121
```

### 4. 下载嵌入模型（可选）

向量检索使用的 `all-MiniLM-L6-v2` 会在首次启动时自动从 HuggingFace 下载（约 80MB）。
如网络受限，可手动下载后设置环境变量 `THINKVAULT_EMBEDDER_MODEL` 指向本地路径。

## 快速开始

```bash
# 启动服务
python -m thinkvault

# 或指定端口
python -m thinkvault --port 8080
```

浏览器访问 `http://localhost:8000` 即可使用。

### CLI 模式

```bash
# 搜索文档
python -m thinkvault search "你的查询" --kb default

# 导出结果
python -m thinkvault search "查询内容" -o result.md
```

## API 概览

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/chat` | POST | 非流式对话 |
| `/api/chat/stream` | POST | SSE 流式对话 |
| `/api/documents/upload` | POST | 上传文档 |
| `/api/documents` | GET | 文档列表 |
| `/api/documents/{id}` | DELETE | 删除文档 |
| `/api/conversations` | GET/POST | 会话列表/创建 |
| `/api/conversations/{id}` | GET/DELETE/PATCH | 会话详情/删除/重命名 |
| `/api/knowledge-bases` | GET | 知识库列表 |
| `/api/model` | GET | 模型状态 |
| `/api/model/load` | POST | 加载模型 |
| `/api/model/unload` | POST | 卸载模型 |
| `/api/hardware` | GET | 硬件信息 |
| `/api/health` | GET | 健康检查 |

## 项目结构

```
thinkvault/
├── core/               # 核心引擎
│   ├── model.py         # 模型封装
│   ├── parser.py        # 文档解析
│   ├── chunker.py       # 文本分块
│   ├── embedder.py      # 向量化
│   ├── storage.py       # 向量存储
│   ├── retriever.py     # 检索模块
│   ├── thinkvault_llm.py # Llama 推理封装
│   ├── document_store.py # 文档元数据
│   ├── conversation_store.py # 对话管理
│   └── db.py            # 数据库基类
├── api/                # FastAPI 接口
│   ├── server.py        # 服务入口
│   ├── routes/          # 路由定义
│   └── schemas.py       # 数据模型
├── webui/              # 前端
│   ├── index.html
│   ├── style.css
│   └── app.js
├── utils/              # 工具
│   ├── hardware.py      # 硬件检测
│   └── logger.py        # 日志
├── test/               # 测试
├── pyproject.toml      # 项目配置
└── requirements.txt    # 依赖清单
```

## Docker 快速启动

### 前置要求

- [Docker](https://docs.docker.com/get-docker/) 20.10+
- [Docker Compose](https://docs.docker.com/compose/install/) 2.0+
- 已下载 GGUF 模型文件，放置在 `~/.thinkvault/models/` 目录

### 一键启动

```bash
# 克隆项目
git clone https://github.com/yourname/thinkvault.git
cd thinkvault

# 准备模型目录（放入 .gguf 文件）
mkdir -p ~/.thinkvault/models
# 将下载的模型文件放入 ~/.thinkvault/models/

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

浏览器访问 `http://localhost:8000`。

### 环境变量说明

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `THINKVAULT_MODEL_PATH` | `~/.thinkvault/models` | 模型文件宿主机目录 |
| `THINKVAULT_API_TOKEN` | (空) | API 认证令牌，留空则关闭认证 |
| `THINKVAULT_CORS_ORIGINS` | `http://localhost:8000` | CORS 白名单，逗号分隔 |
| `THINKVAULT_RATE_LIMIT` | `60` | 每窗口最大请求数 |
| `THINKVAULT_RATE_WINDOW` | `60` | 速率限制窗口(秒) |

### GPU 加速

取消 `docker-compose.yml` 中 GPU 相关注释，并安装 [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)：

```bash
# 安装 nvidia-container-toolkit 后
docker-compose up -d
```

## 实际使用截图

> 以下为 ThinkVault Web UI 截图占位说明，实际截图请替换为项目中的真实图片。

### 主界面 — 文档上传与知识库管理

![主界面](docs/screenshots/main_ui.png)

主界面左侧为知识库列表，支持创建多个知识库并将不同类型的文档归类管理。右侧为文档上传区，支持拖拽上传 PDF、DOCX、TXT 等多种格式。

### 对话界面 — SSE 流式问答

![对话界面](docs/screenshots/chat_ui.png)

选择知识库后，输入自然语言问题，系统自动检索相关文档片段并生成回答。支持逐 Token 流式输出，响应迅速。

### 模型管理 — 加载/卸载/状态监控

![模型管理](docs/screenshots/model_ui.png)

实时查看 LLM 模型加载状态、显存/内存占用，支持一键加载和卸载模型。

## CLI 使用示例

ThinkVault 提供命令行工具用于快速检索和文档管理。

### 语义搜索

```bash
# 基础搜索
python -m thinkvault search "ThinkVault 的核心架构是什么？" --kb default

# 输出示例：
# ===== 检索结果 =====
# [来源: 01_技术架构说明.txt] (BM25 得分: 12.45)
# ThinkVault 采用模块化设计，主要包含文档解析层、文本分块层、
# 向量化层、检索引擎和 LLM 推理层...
#
# [来源: 02_ThinkVault项目说明.md] (向量距离: 0.12)
# 混合检索：BM25 关键字匹配 + 向量语义检索，取长补短...
#
# 共检索到 3 个相关片段
```

### 导出搜索结果

```bash
# 导出为 Markdown
python -m thinkvault search "销售数据统计" -o result.md
```

### 知识库管理

```bash
# 列出所有知识库
python -m thinkvault kb list

# 输出示例：
# ===== 知识库列表 =====
# 1. default          文档: 12  分块: 156
# 2. 技术文档          文档: 5   分块: 89
# 3. 会议纪要          文档: 8   分块: 42
```

### 模型管理

```bash
# 查看模型状态
python -m thinkvault model status

# 输出示例：
# ===== 模型状态 =====
# 模型: Llama-3.2-3B-Instruct-Q4_K_M.gguf
# 状态: 已加载
# 显存占用: 2.1 GB
```

## 常见问题 (FAQ)

### Q1: 启动后报 "gguf-chat 未安装"？

`gguf-chat` 为非 PyPI 包，需从项目仓库手动安装。请参考项目内 `gguf-chat` 目录的安装说明，或联系维护者获取 wheel 包。

### Q2: ChromaDB 在 Windows 上报权限错误？

设置 `THINKVAULT_DATA_DIR` 指向一个有写入权限的目录：

```bash
set THINKVAULT_DATA_DIR=D:\thinkvault_data
python -m thinkvault
```

### Q3: Cross-encoder 模型下载失败？

首次使用时会从 HuggingFace 下载 `ms-marco-MiniLM-L-6-v2` 模型（约 80MB）。如果网络受限：

1. 手动下载模型到本地目录
2. 设置环境变量指向本地路径：

```bash
set THINKVAULT_CROSS_ENCODER=/path/to/local/model
```

如果不需要重排序功能，此错误不影响基础检索使用。

### Q4: 如何确认API服务正常运行？

```bash
curl http://localhost:8000/api/health
# 返回: {"status":"ok"}
```

### Q5: 支持哪些文档格式？

| 格式 | 扩展名 | 最低依赖 |
|------|--------|----------|
| PDF | .pdf | pymupdf |
| Word | .docx | python-docx |
| PowerPoint | .pptx | python-pptx（可选） |
| Excel | .xlsx / .xlsm | openpyxl（可选） |
| 纯文本 | .txt | 内置 |
| Markdown | .md | 内置 |

### Q6: 如何重置所有数据？

```bash
# 停止服务后删除数据目录
rm -rf /data/chroma /data/uploads /data/conversations
# 或 Docker 环境:
docker-compose down -v
```

### Q7: 内存占用过高怎么办？

- 使用更小的嵌入模型：设置环境变量指向轻量模型
- 使用量化程度更高的 GGUF 模型（如 Q2_K 版本）
- 减少 `chunk_size` 和 `top_k` 值

### Q8: 如何贡献代码？

1. Fork 项目仓库
2. 创建特性分支：`git checkout -b feature/your-feature`
3. 确保测试通过：`python test/run_integration.py`
4. 提交 Pull Request

## License

MIT License