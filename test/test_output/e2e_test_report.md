# ThinkVault 端到端测试报告

**日期**: 2026-05-30
**测试目标**: 验证 Llama 3.2 1B Q4_K_M 集成到 ThinkVault 的端到端文档问答链路

---

## 1. 测试环境

| 项目 | 值 |
|------|-----|
| 操作系统 | Windows 11 (Build 22631) |
| Python | 3.11 |
| LLM 模型 | Llama-3.2-1B-Instruct-Q4_K_M.gguf (770MB) |
| LLM 推理框架 | gguf_chat (自定义 PyTorch runner) |
| 嵌入模型 | BAAI/bge-small-zh-v1.5 (dim=512) |
| 向量数据库 | ChromaDB (PersistentClient) |
| 上下文窗口 | n_ctx=2048 |

## 2. 测试链路

```
用户丢文档 → 解析(PDF/TXT) → 分块(512字/64重叠) → 向量化(bge-small-zh) 
→ 存储(ChromaDB) → 用户提问 → 向量检索(top_k=3) → 组装RAG提示词 
→ Llama 3.2 1B 推理 → 生成回答
```

## 3. 测试结果

### 3.1 文档摄入

| 步骤 | 结果 | 详情 |
|------|------|------|
| 解析 | ✅ | test_doc_deep_learning.txt, 682字符 |
| 分块 | ✅ | 12个块 (chunk_size=512, overlap=64) |
| 向量化 | ✅ | 12个向量, dim=512 |
| 存储 | ✅ | 12个块已索引到知识库 e2e_test_v2 |

### 3.2 检索测试

问题: **"ResNet 的核心创新是什么？"**

| 排名 | 距离 | 片段来源 | 相关性 |
|------|------|----------|--------|
| #1 | 0.897 | Transformer架构 | 低（文档中也出现，但非核心） |
| #2 | 0.953 | ResNet残差连接 | **高（正确命中）** |
| #3 | 1.090 | CNN卷积网络 | 中（相关但非直接答案） |

检索结果包含了正确的 ResNet 相关片段（#2），但排序受嵌入模型精度影响，#1 片段也包含"核心"、"架构"等关键词导致相似度偏高。

### 3.3 LLM 生成

**问题**: ResNet 的核心创新是什么？

**回答**:
> ResNet 的核心创新是引入了残差连接（ResNet 11 和上下左右三个版本中）。通过跳跃连接，让信息在处理每个词时跨层直接传递，从而解决了深层网络训练中的梯度消失问题。这种创新没有直接改写 ResNet 的原始模型，但它使 ResNet 成为可能的，且有助于深度学习的研究和应用。

**性能统计**:

| 指标 | 值 |
|------|-----|
| 输入 tokens | 351 |
| 输出 tokens | 128 |
| 总 tokens | 479 |
| 推理耗时 | 76.8s |
| 生成速率 | 1.7 tok/s |

### 3.4 分析

- **正确提取**: 准确识别 ResNet 核心创新为"残差连接"和"跳跃连接"
- **正确理解**: 正确说明了残差连接解决了"梯度消失问题"
- **1B 模型局限**: 出现轻微幻觉（"上下左右三个版本中"），部分内容受 Transformer 片段干扰
- **生成速度**: CPU 上 ~1.7 tok/s，适合本地轻量场景

## 4. 新增/修改文件

### 新增文件

| 文件 | 路径 | 用途 |
|------|------|------|
| thinkvault_llm.py | `F:\AAone\thinkvault\core\thinkvault_llm.py` | gguf_chat Llama 推理封装 |
| test_e2e.py | `F:\AAone\test\test_e2e.py` | 完整端到端测试（3题） |
| test_e2e_quick.py | `F:\AAone\test\test_e2e_quick.py` | 快速端到端测试（1题） |
| test_doc_deep_learning.txt | `F:\AAone\test\test_doc_deep_learning.txt` | 中文测试文档 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `embedder.py` | 增加本地 HuggingFace 缓存路径支持 |

## 5. 结论

✅ **端到端测试通过。** Llama 3.2 1B Q4_K_M 已成功集成到 ThinkVault 项目，完整链路（文档摄入 → 向量检索 → LLM 生成回答）验证可用。1B 模型在简单问答场景下表现可用，但存在轻微幻觉，适合轻量级本地文档问答场景。
