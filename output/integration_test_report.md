# ThinkVault V2.0 集成测试报告

- **执行时间**: 2026-06-01 04:17:50
- **总耗时**: 4.2s
- **服务启动**: ✅ 成功 (3.9s)
- **测试结果**: ❌ 存在失败

## 测试套件: test_v2.py

| 测试类 | 预期用例数 | 状态 |
|--------|-----------|------|
| TestServerV2 | 2 | — |
| TestConversationAPI | 6 | — |
| TestSSEStreaming | 3 | — |
| TestPDFSupport | 2 | — |
| TestModelAPI | 2 | — |
| TestFullRegression | 4 | — |
| **合计** | **19** | — |

> 详细输出见上方控制台日志。

## 备注

- 测试服务器地址: http://127.0.0.1:8000
- 所有 Conversation / Document 测试数据已在用例中自动清理
- ⚠️ 部分测试未通过，请查看上方 pytest 输出