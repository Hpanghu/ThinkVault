"""
测试：文档解析器
覆盖 PDF / DOCX / TXT / MD 格式解析
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from thinkvault.core.parser import DocumentParser, ParsedDocument

TEST_DIR = Path(__file__).parent
OUTPUT_DIR = TEST_DIR / "test_output"
OUTPUT_DIR.mkdir(exist_ok=True)


@pytest.fixture(autouse=True, scope="module")
def _setup_test_files():
    """确保测试文件在测试运行前创建"""
    create_test_files()
    yield


def create_test_files():
    """创建测试用文件"""
    # TXT 测试文件
    txt_content = """ThinkVault 项目简介

ThinkVault 是一个个人 AI 工作台，旨在将本地文档转化为可对话的知识库。

核心功能：
1. 本地模型推理
2. 文档上传和解析
3. 文档问答（RAG）
4. 知识库管理

技术栈：
- 后端：Python + FastAPI
- 推理引擎：llama.cpp
- 向量数据库：ChromaDB
- Embedding: bge-small-zh

本项目不会将任何数据上传到云端，所有处理均在本地完成。"""
    (OUTPUT_DIR / "test_intro.txt").write_text(txt_content, encoding="utf-8")

    # MD 测试文件
    md_content = """# ThinkVault

> 个人 AI 工作台

## 安装

```bash
pip install -r requirements.txt
```

## 使用

1. 启动服务
2. 上传文档
3. 开始提问
"""
    (OUTPUT_DIR / "test_readme.md").write_text(md_content, encoding="utf-8")

    print("[OK] 测试文件已创建")


def test_parse_txt():
    """TXT 解析测试"""
    file_path = OUTPUT_DIR / "test_intro.txt"
    doc = DocumentParser.parse(str(file_path))

    assert doc.parse_error is None, f"解析错误: {doc.parse_error}"
    assert doc.file_type == "txt"
    assert len(doc.paragraphs) > 0
    assert "ThinkVault" in doc.raw_text
    assert "本地模型推理" in doc.raw_text
    print(f"[PASS] TXT 解析: {len(doc.paragraphs)} 段落, {len(doc.raw_text)} 字符")


def test_parse_markdown():
    """MD 解析测试"""
    file_path = OUTPUT_DIR / "test_readme.md"
    doc = DocumentParser.parse(str(file_path))

    assert doc.parse_error is None, f"解析错误: {doc.parse_error}"
    assert doc.file_type == "md"
    assert "ThinkVault" in doc.raw_text
    assert "pip install" in doc.raw_text
    print(f"[PASS] MD 解析: {len(doc.paragraphs)} 段落")


def test_parse_nonexistent():
    """解析不存在的文件"""
    doc = DocumentParser.parse(str(OUTPUT_DIR / "does_not_exist.pdf"))
    assert doc.parse_error is not None
    assert "不存在" in doc.parse_error
    print(f"[PASS] 不存在文件: {doc.parse_error}")


def test_parse_unsupported():
    """解析不支持的格式"""
    unsupported = OUTPUT_DIR / "test.xyz"
    unsupported.write_text("dummy")
    doc = DocumentParser.parse(str(unsupported))
    assert doc.parse_error is not None
    assert "不支持" in doc.parse_error
    unsupported.unlink()
    print(f"[PASS] 不支持的格式: {doc.parse_error}")


def test_parse_empty_txt():
    """解析空文件"""
    empty_file = OUTPUT_DIR / "test_empty.txt"
    empty_file.write_text("", encoding="utf-8")
    doc = DocumentParser.parse(str(empty_file))
    assert doc.parse_error is None
    assert doc.is_empty
    print(f"[PASS] 空文件: is_empty={doc.is_empty}")


if __name__ == "__main__":
    create_test_files()
    print("=" * 50)
    test_parse_txt()
    test_parse_markdown()
    test_parse_nonexistent()
    test_parse_unsupported()
    test_parse_empty_txt()
    print("=" * 50)
    print("文档解析器测试完成")
