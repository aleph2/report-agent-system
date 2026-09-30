# Strict 实际请求与 agent 反馈恢复 v1.6

2026-09-30；承接 v1.5。Main 实施、测试与运行；architecture_review_v1 聚焦独立审阅。

第四次恢复使用精确结构错误反馈，agent 自主修正调用；数据库已有 8 条 Criterion（含 agent 自行探测产生的 2 条记录）、5 个 ContentNode、5 条 Relation、1 条 DelegatedTask，writer 已实际开始工作。尚无整稿最终审核，不据此声称报告质量通过。

实际 HTTP 层记录确认：协调者发往 `https://api.deepseek.com/beta/chat/completions`，33 个函数全部 `strict=true`；writer 为 29 个函数全部 strict。两者均 `deepseek-flash`、thinking enabled、max、max_tokens=131072、stream=false、parallel_tool_calls=false。schema 按摘要保存在项目本地，日志排除请求头、API key、消息内容及推理文本。

## Strict 的实际边界

首次合成请求成功不能证明格式约束必然执行。真实请求 sequence 217、222 携带上述 strict 参数，但 response 218 的 previous_ref=null、response 223 的 previous_ref 缺失仍违反相应线格式；响应也出现多工具调用。本地未执行非法项，并正常串行执行合法兄弟项。

不能把 strict/parallel_tool_calls 参数当作运行结果保证；尚不能仅凭此确定供应商内部原因。未关闭 strict，也未放松业务校验。

独立协议诊断：max/8192 单值枚举冲突探针用完 8192 输出 token、没有工具调用，结果不可用于判断 strict 执行；非法 schema 输入得到 HTTP 400。该组成功返回用量 8526 token，另一个请求未返回计费统计。没有盲目重复冲突实验。

## 改进与验证

解码错误补充真实字段路径、缺失/多余字段和类型；联合类型优先展示标签匹配分支的诊断，仍尝试所有合法分支，不猜测或修复参数。实际推进：response 223 缺 previous_ref → 错误反馈 → response 228 合法提交 → response 235 提交完整六项标准。response 240 正文 body 仍用旧字典 → missing entries 反馈 → 后续正文成功保存。改进是上下文反馈作用，不是模型权重学习。

补上结构化结果、普通合法调用与 invalid 同批时的原生结束路由边界：合法调用执行一次，结束前把未消费的 invalid 反馈交给模型，清除提前产生的 structured_response；保留原始消息与回执。23 项离线测试通过（14.02 秒），覆盖该混合批次、HTTP 审计脱敏、字段诊断及既有 strict/native 回归。

最后一项结束路由修复在第四次运行启动后完成，当前在途进程尚未加载；不为此打断正在产出的 writer。如果本轮出现该混合结束批次，不认可其结果为完整审核，使用新代码检查点恢复。下一次进程启动生效。

## 缺陷处置

- P2：错误过于笼统造成 agent 多次尝试错误包装；可通过真实反馈恢复。已补诊断，真实标准/正文保存验证有效，不阻断继续生成。
- P2：混合结构化结束路由可能漏掉反馈；不能再仅凭 parallel_tool_calls=false 隔离。已修复并通过原生反例测试；在途运行按上段边界监控。负责人 Main；阻断受影响批次的完整审核认定，不阻断未受影响写作。

历史失败和用量全部保留；第三次重复错误运行已主动中断。用户 .env、旧系统和旧服务未变。

独立增量复核结论：未发现阻断下一次启动的偏差；新测试覆盖有效兄弟仅执行一次、反馈进入第二次模型和最终采用第二份结构化输出。评审者未独立重跑测试，强调当前在途进程未加载补丁的边界，Main 接受并保留该限制。
