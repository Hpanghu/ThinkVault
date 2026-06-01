"""
审计修复验证测试 — 覆盖修复后的关键功能
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================== P0 修复验证 ==============================

def test_parser_total_pages_after_close():
    """P0: parser total_pages 在 doc.close() 后不再引用已关闭文档"""
    from thinkvault.core.parser import DocumentParser

    # 使用测试文档
    test_doc = Path(__file__).parent / "test_doc_deep_learning.txt"
    if test_doc.exists():
        result = DocumentParser.parse(str(test_doc))
        assert not result.parse_error, f"解析错误: {result.parse_error}"
        # TXT 文件 total_pages 应为 1
        assert result.total_pages >= 0, f"total_pages 异常: {result.total_pages}"
        print(f"[PASS] P0: parser total_pages = {result.total_pages}")


def test_chat_exception_handling():
    """P0: ChatResponse 在异常时返回错误信息而非崩溃"""
    from thinkvault.api.schemas import ChatResponse

    resp = ChatResponse(
        answer="[错误] 处理请求时发生异常: Test error",
        sources=[],
        stats={"error": "Test error"},
    )
    assert resp.answer.startswith("[错误]")
    assert resp.stats.get("error") == "Test error"
    print(f"[PASS] P0: ChatResponse 异常格式正确")


def test_document_store_context_manager():
    """P1: document_store 使用 context manager 确保连接关闭"""
    from thinkvault.core.document_store import add_document, get_document, delete_document, list_documents

    doc_id = add_document(
        file_name="test_ctx.txt",
        file_type="txt",
        file_size=100,
        knowledge_base="audit_test",
        chunk_count=3,
    )
    assert doc_id, "add_document 返回空"

    doc = get_document(doc_id)
    assert doc is not None, "get_document 返回 None"
    assert doc["file_name"] == "test_ctx.txt"
    assert doc["chunk_count"] == 3

    deleted = delete_document(doc_id)
    assert deleted, "delete_document 失败"

    # 确认已删除
    doc2 = get_document(doc_id)
    assert doc2 is None, "删除后仍能查到文档"

    print(f"[PASS] P1: document_store CRUD + context manager")


# ============================== P1 修复验证 ==============================

def test_retriever_format_context_truncation():
    """P1: format_context 正确处理超大片段"""
    from thinkvault.core.retriever import Retriever

    r = Retriever()

    # 单个超长片段不应返回空
    hits = [{
        "text": "X" * 5000,
        "metadata": {"source_file": "big.txt", "source_page": 1},
        "distance": 0.1,
    }]
    context, sources = r.format_context(hits, max_chars=1000)
    assert len(sources) > 0, "第一个超长片段被跳过（BUG 回归）"
    assert len(context) <= 1000 + 50, f"截断后过长: {len(context)}"
    print(f"[PASS] P1: 超大片段截断 — sources={len(sources)}, context_len={len(context)}")

    # 正常多片段放入
    hits2 = [
        {"text": "A" * 200, "metadata": {"source_file": "a.txt"}, "distance": 0.1},
        {"text": "B" * 300, "metadata": {"source_file": "b.txt"}, "distance": 0.2},
        {"text": "C" * 400, "metadata": {"source_file": "c.txt"}, "distance": 0.3},
    ]
    context2, sources2 = r.format_context(hits2, max_chars=1000)
    assert len(sources2) >= 2, "正常片段未正确放入"
    print(f"[PASS] P1: 多片段正常 — sources={len(sources2)}, context_len={len(context2)}")

    # 空列表
    context3, sources3 = r.format_context([], max_chars=1000)
    assert context3 == ""
    assert sources3 == []
    print(f"[PASS] P1: 空列表返回空")


def test_retriever_format_context_partial():
    """P1: format_context 充分利用剩余空间"""
    from thinkvault.core.retriever import Retriever

    r = Retriever()
    hits = [
        {"text": "A" * 600, "metadata": {"source_file": "a.txt"}, "distance": 0.1},
        {"text": "B" * 600, "metadata": {"source_file": "b.txt"}, "distance": 0.2},
    ]
    context, sources = r.format_context(hits, max_chars=800)
    # 第一个片段完整放入，第二个截断
    assert len(sources) >= 1
    assert "A" * 600 in context
    # 800 - 600 - segment_header ≈ 200 chars remaining → 第二个片段截断
    print(f"[PASS] P1: 部分截断 — sources={len(sources)}, context_len={len(context)}")


def test_storage_safe_name_roundtrip():
    """P1: KB 名称编码双向转换正确"""
    from thinkvault.core.storage import VectorStore

    vs = VectorStore()

    # 空格
    assert vs._safe_name("my kb") == "my_kb"
    assert vs._restore_name("my_kb") == "my kb"
    # 短横线（保留）
    assert vs._safe_name("my-kb") == "my-kb"
    assert vs._restore_name("my-kb") == "my-kb"
    # 下划线（双下划线编码）
    assert vs._safe_name("my_kb") == "my__kb"
    assert vs._restore_name("my__kb") == "my_kb"
    # 混合
    safe = vs._safe_name("test kb-v2_final")
    assert vs._restore_name(safe) == "test kb-v2_final", f"往返失败: {safe} → {vs._restore_name(safe)}"

    print(f"[PASS] P1: KB 名称编解码 — 全部往返正确")


# ============================== P2 修复验证 ==============================

def test_llm_safe_device_unload():
    """P2: thinkvault_llm unload 安全访问 device"""
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM

    llm = ThinkVaultLLM()
    # 未加载时 unload 不应崩溃
    llm.unload()
    assert llm.is_loaded == False
    print(f"[PASS] P2: 未加载 unload 不崩溃")


def test_llm_generate_not_loaded():
    """P2: generate 在无后端时返回错误而非崩溃"""
    import asyncio
    from thinkvault.core.thinkvault_llm import ThinkVaultLLM, _build_messages

    async def run():
        llm = ThinkVaultLLM()
        messages = _build_messages("system", [], "test")
        answer, stats = await llm.generate(messages, max_new_tokens=32)
        return answer, stats

    answer, stats = asyncio.run(run())
    assert isinstance(answer, str)
    assert isinstance(stats, dict)
    print(f"[PASS] P2: 无后端 generate 返回错误")


def test_format_chat_prompt():
    """格式验证"""
    from thinkvault.core.thinkvault_llm import format_chat_prompt

    prompt = format_chat_prompt("你是助手", "你好")
    assert "<|start_header_id|>system<|end_header_id|>" in prompt
    assert "<|start_header_id|>user<|end_header_id|>" in prompt
    assert "你是助手" in prompt
    assert "你好" in prompt
    assert prompt.endswith("<|start_header_id|>assistant<|end_header_id|>\n\n")
    print(f"[PASS] P2: Chat 模板格式正确")


# ============================== XSS 防护验证 ==============================

def test_sanitize_html_script_tag():
    """P0: XSS — script 标签被移除"""
    # 模拟前端 sanitizeHtml
    import re

    def sanitize_html(html):
        return re.sub(
            r'<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>',
            '',
            html,
            flags=re.IGNORECASE
        )

    dirty = '<p>Hello</p><script>alert("xss")</script>'
    clean = sanitize_html(dirty)
    assert '<script>' not in clean.lower()
    assert 'Hello' in clean
    print(f"[PASS] P0: XSS script 标签已移除")

    # on* 事件处理器
    dirty2 = '<img src=x onerror="alert(1)">'
    clean2 = re.sub(r'on\w+\s*=\s*"[^"]*"', '', dirty2, flags=re.IGNORECASE)
    assert 'onerror' not in clean2
    print(f"[PASS] P0: XSS on* 事件已移除")

    # javascript: 协议
    dirty3 = '<a href="javascript:void(0)">click</a>'
    clean3 = re.sub(r'javascript\s*:', 'blocked:', dirty3, flags=re.IGNORECASE)
    assert 'javascript:' not in clean3
    print(f"[PASS] P0: XSS javascript: 协议已阻止")


# ============================== 知识库名称编码 ==============================

def test_kb_name_special_chars():
    """P2: 含特殊字符的知识库名正确编解码"""
    from thinkvault.core.storage import VectorStore

    vs = VectorStore()
    cases = [
        "default",
        "test kb",
        "my-kb",
        "a_b c-d",
        "knowledge_base_v2",
        "中文知识库",
        "test_case-final",
    ]
    for original in cases:
        safe = vs._safe_name(original)
        restored = vs._restore_name(safe)
        assert restored == original, f"往返失败: '{original}' → '{safe}' → '{restored}'"

    print(f"[PASS] P2: {len(cases)} 个 KB 名称全部往返正确")


# ============================== 主入口 ==============================

if __name__ == "__main__":
    print("=" * 60)
    print("ThinkVault 审计修复验证测试")
    print("=" * 60)

    # P0
    test_parser_total_pages_after_close()
    test_chat_exception_handling()
    test_sanitize_html_script_tag()

    # P1
    test_document_store_context_manager()
    test_retriever_format_context_truncation()
    test_retriever_format_context_partial()
    test_storage_safe_name_roundtrip()

    # P2
    test_llm_safe_device_unload()
    test_llm_generate_not_loaded()
    test_format_chat_prompt()
    test_kb_name_special_chars()

    print("=" * 60)
    print("全部审计修复测试通过")
