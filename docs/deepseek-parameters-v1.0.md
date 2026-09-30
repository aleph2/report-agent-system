# DeepSeek 调用参数 v1.0

2026-09-30；适用 Task059 官方 DeepSeek 隔离测试。API key 不进入文档或日志。

| 参数 | 文本模型（协调、写作、审核及文本工具） | 图像观察 |
|---|---|---|
| model | deepseek-flash | deepseek-flash |
| base_url | https://api.deepseek.com/beta | https://api.deepseek.com |
| endpoint | /chat/completions | /chat/completions |
| thinking | {"type":"enabled"} | 不传 |
| reasoning_effort | max | 不传 |
| max_tokens | 131072 | 32768 |
| stream | false | false |
| parallel_tool_calls | false | 不传，无 tools |
| tools[*].function.strict | 全部 true | 不适用 |
| tool_choice | 通常不传；框架强制选择转换为 auto | 不传 |
| response_format | 不传；grader 用 HierarchicalResponse 工具 | 不传 |
| image detail | 不适用 | high |
| SDK max_retries | 0 | 0 |
| timeout connect/read/write/pool | 15/1800/60/60 秒 | 相同 |

temperature、top_p、stop、presence_penalty、frequency_penalty 未显式传入。messages、tools 随实际职责和任务变化。没有整轮任务超时或累计 token 配额；记录用量。

用户 `.env` 保持不变。试验启动器显式设置 REPORT_DEEPSEEK_STRICT=1，文本适配器切换至官方 /beta；视觉客户端保留原 endpoint。

Strict 线格式版本为 deepseek-strict-v1：明确字段继续保留；可选字段以 absent/present 区分省略与 null；开放字典以 entries 表达；任意 JSON 容器递归表达。返回后确定性还原为原业务参数，仍受本地类型、权限、引用和事务检查。原始模型调用线格式用于后续对话重放，旧检查点的旧调用不改写。

格式或解码失败产生同 ID、未执行的工具错误反馈，agent 自主决定纠正、换行动或结束。代码不自动补参数或重放写操作。Strict 不证明事实、引用或审核判断正确。

验证：20 项离线测试通过；官方接口的一次合成兼容性调用接受了实际 34 个工具定义（包括框架工具、commit_objects 和 HierarchicalResponse），返回合法 commit_objects，开放字典与省略字段成功还原，未执行该调用。该探针为 low/8192、总 20416 token，用于协议验证，不能与 max 正式报告质量测试混为一谈。

依据：[DeepSeek Tool Calls strict 官方说明](https://api-docs.deepseek.com/zh-cn/guides/tool_calls/)。
