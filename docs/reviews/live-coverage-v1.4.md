# 干净生成实测与工具参数恢复 v1.4

2026-09-30。承接 [v1.3](live-coverage-v1.3.md)，用户邮件进一步确认只复用原件、OCR及委托，其余重新开始。完整实例 `.runs/task059/deepseek-end-to-end-v2`：9源、1617精确定位块，逐源数量/摘要核验；启动时0内容对象。第一轮运行12:46—12:59，使用官方deepseek-flash、thinking/max，未调用旧报告或旧标准。

## 实际结果与诊断

首次完整运行停于needs_attention，无服务超时、无最终审核。29次文本请求/响应，供应商返回文本用量3,297,518 tokens（prompt 3,165,606，completion 131,912）；3次视觉观察用量29,876（prompt 3,797，completion 26,079）。不另加已包含的reasoning tokens。

协调者自主调查模板、指南、设计和地勘，报告了源间差异并拟定标准。这些是模型观察和候选工作，不是独立核验的工程结论。实际仅提交2个Requirement与9个SourceArtifact；0个Criterion、0个ContentNode。两次标准提交因引用字段结构被拒绝；终末commit_objects参数JSON不合法，进入AIMessage.invalid_tool_calls，未执行写入。当前LangChain路由只看到有效tool_calls为空，因此结束。尚未进入grader，不能据此判断审核质量。

确认P2：公开提交工具原为list[dict]，未向模型完整暴露kind、qualifiers、provenance_kind、引用结构等契约，造成无效参数及可恢复的流程停顿。另有原生框架本次turn不将invalid_tool_calls送回模型的问题；阻断本次完整报告交付，但可保留现场并经验证从检查点恢复，不需要重做OCR或人工代写。Main负责修复工具schema；模型仍自行选择动作、构造内容和纠错。

## 最小修复与边界

新增content_inputs从已有业务模型字段派生四类提交输入，明确类型枚举及Ref/client_key，Requirement与SourceArtifact引用按既有存储约束区分；服务端ContentStore仍负责权限、版本、引用闭包和事务，不复制语义validators。未改角色提示词、验收标准或工程答案。

原生DeepAgents已提供PatchToolCallsMiddleware.before_agent：再次调用同检查点时，为未配对的无效调用追加同ID错误反馈，保留原始坏参数，不执行或修复它。复用此机制，没有新增自定义恢复循环。旧结果和调用配置在恢复前单独留存。一般错误日志中的EXECUTION_FAILED只是安全摘要；模型此前实际已收到INVALID_CONTRACT的字段反馈，不能误称所有错误都被隐藏。

Main离线三组回归25 passed / 11.24秒。新增用例验证公开schema、拒绝错误字段类型、批内引用、同检查点原始坏参数保留、真实错误消息配对、无效操作零写入、新合法调用才提交。独立复核 `/root/architecture_review_v1` 核对代码与测试，未发现本轮恢复阻断；未独立重跑或做工程质量签发。

官方机制参考：[LangChain自定义中间件](https://docs.langchain.com/oss/python/langchain/middleware/custom)；上游同类问题记录 [invalid_tool_calls路由](https://github.com/langchain-ai/langchain/issues/33504)。本轮根因以本地安装源码、实际审计和离线重现为准。

目前仍需完成恢复后的生成、最终审核及独立结果核验，以上不构成质量通过。
