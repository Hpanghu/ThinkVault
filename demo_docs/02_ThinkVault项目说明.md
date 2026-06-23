# ThinkVault 项目说明

## 项目背景

在日常工作中，我们积累了大量的技术文档、会议纪要、产品规格书和数据分析报告。
传统的关键词搜索无法理解语义，而商业知识库产品往往需要将数据上传至云端，
存在隐私泄露风险。

**ThinkVault** 应运而生 — 一款完全本地运行的智能知识库系统。

## 核心功能

### 1. 多格式文档支持

| 格式 | 扩展名 | 解析引擎 |
|------|--------|----------|
| PDF 文档 | .pdf | PyMuPDF |
| Word 文档 | .docx | python-docx |
| PowerPoint 演示 | .pptx | python-pptx |
| Excel 表格 | .xlsx / .xlsm | openpyxl |
| 纯文本 | .txt | 内置 |
| Markdown | .md | 内置 |

### 2. 智能检索

- **混合检索**：BM25 关键字匹配 + 向量语义检索，取长补短
- **重排序**：Cross-encoder 对候选结果精细打分
- **意图识别**：自动判断用户输入是否需要检索知识库

### 3. 对话管理

- 多会话支持（创建、重命名、删除）
- 消息持久化（SQLite），重启不丢失
- SSE 流式输出，逐 Token 返回

### 4. 安全与隐私

- 全本地运行，数据不出机器
- API Token 认证（可选）
- 基于 IP 的速率限制
- CORS 白名单控制

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python -m thinkvault

# 浏览器访问
open http://localhost:8000
```

## 技术栈

- **后端**：Python 3.10+, FastAPI, Uvicorn
- **推理后端**：llama-cpp-python server (OpenAI 兼容), BGE (sentence-transformers)
- **存储**：ChromaDB (向量), SQLite (元数据)
- **前端**：原生 HTML/CSS/JS (无框架依赖)

## 许可证

MIT License - 自由使用、修改和分发。
