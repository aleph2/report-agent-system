# 真实数据测试与 strict 接入 v1.5

2026-09-30，Main 实施；architecture_review_v1 独立只读审阅。

## 当前业务结果

`.runs/task059/deepseek-end-to-end-v2` 仅继承原始资料、已核实 OCR/位置和原始委托。前两次运行共 33 次文本模型响应；尚无已保存 Criterion、ContentNode 或最终审核。第二次恢复仍在标准提交时出现非法 JSON，非超时，不能归因于 grader；grader 尚未被调用。

第二次结束时文本累计 3804037 token；图像观察累计 29876 token。模型做了资料调查并提出标准，但其语义结论尚未独立证实。

## 本次变更

- 原生 after_model 中发现 invalid_tool_calls 时，复用框架错误消息并补充真实 JSON 解析位置；同轮给 agent 反馈。合法兄弟调用正常执行，非法调用不执行，不自动修复或重试。
- 历史检查点的原生恢复错误同样补充诊断，保留原始调用。模型可以选择不再执行该动作。
- 按用户授权启用 DeepSeek 官方 /beta 与所有 function strict=true。新增独立可逆线格式，保留省略/null/开放字典/任意 JSON 的区别；不改变业务所有权与权限。
- 保存原始 strict 调用参数用于历史重放，解码失败也作为未执行反馈。测试发现并修复框架不保留原始 tool_calls 的适配问题。
- [完整调用参数 v1.0](../deepseek-parameters-v1.0.md)。用户 .env 和旧服务均未修改。

## 证据与边界

`test_deepseek_strict.py`、`test_content_tool_inputs.py`、`test_hierarchical_runtime.py`、`test_official_deepseek.py` 共 20 项通过。覆盖所有职责/原生工具 schema、本地委派、可选/嵌套值往返、多轮原始参数重放、非法与合法兄弟调用以及 strict grader 保存链。

官方合成探针发送 34 个工具定义，服务端接受并返回合法 commit_objects；0 invalid，成功还原业务参数，未执行写入。探针 low/8192，20416 token，不能证明实际 max 报告质量或完整端到端通过。原始脱敏协议记录保存在 `.analysis/task059/strict-probe/`。

独立评审认可转换、回放、权限和错误反馈边界，无阻断兼容性探针问题；服务端递归/null/schema 支持随后由上述探针验证。最终结构化结果保存目前是离线证据。

## 缺陷处置

- P2：原生 invalid-only 回复导致提前结束，阻断连续推进但可检查点恢复；本轮同轮错误反馈已修复并测试，真实恢复待继续。
- P2：同批包含合法结构化响应、普通工具及 invalid 时，框架可能提前结束。当前 parallel_tool_calls=false，正常服务不应返回此混合批次；保留为可隔离边界，不阻断当前单调用试验。若实际出现，不认可该轮为完整审核，补充原生路由验证。负责人 Main。
- 先前 OCR 索引缺陷已通过新隔离输入修复，历史失败证据保留在 v1.3；不覆盖其结论。

本版本记录接入与验证，尚不表示报告生成、审核质量或工程签发已通过。
