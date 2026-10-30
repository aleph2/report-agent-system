# Neo 独立复核：Agent I/O 同类路径回归与合成实模探针

状态：本轮验证完成；两个 P2 保留开放；未修改应用，未批准启动原 batch1 重构。

## 结论

本次证明的是所选真实程序路径的 I/O、权限/身份反例，以及四次合成输入下的模型返回结构。不能据此宣称全部 44 项职责、全部接口/条件、报告内容、工程分值、长资料覆盖或稳定性已验收。保留失败反例，不以 xfail 或更改需求获得“全绿”。Neo 只读取源码、测试和回执，并写本文件；Main 执行测试与真实调用。

## 离线结果与有效范围

- siblings-v2：103 个用例，102 通过、1 失败。
- state-and-identity-v2：18 个用例全部通过。
- summary-lifecycle：2 个用例，1 通过、1 失败。
- 合计 123 个唯一 nodeid：121 通过、2 失败。lifecycle-proof 是 artifact 两例的加强复跑，不重复增加分母。
- 上述三个主结果的应用源码前后摘要一致；记录中没有网络拒绝事件，测试模型为 fake/MockTransport。此陈述不等于全进程/子进程网络审计或全部路径覆盖。

新增 sibling 测试经过真实 run_report/native 委派/角色工具/下一模型输入；独立文字工具的实际材料和返回另有旁观记录。fixture 以固定合成正文、尾部条件、限定信息为 oracle，不把当前投影函数当预期答案，不允许 fake Agent 的后续补救替代原始断言。涉及错误的测试按业务 envelope 和精确错误码判断，不将 ToolMessage transport status 单独当业务成功。

首轮错误 envelope 读取层级、委派注册前取对象基线，以及 offline-v1 返回未注册 read_source，均为测试/runner 问题；原失败保留。修正的是 fixture/oracle，不是产品失败的“修复”。state 首次收集节点名错误同样保留，不计产品缺陷。

## 两个已复现的开放问题

### NFR-05 — P2：artifact 外层生命周期丢失已知未派发分类

- 位置：src/report_agent/artifact_review.py:207–222；共享 src/report_agent/evidence_analysis.py:141、185–189；已有 src/report_agent/bounded_operations.py:49 起。
- 触发：合法 artifact 审核请求在实际 SDK admission hook 因授权 token 不足被拒绝，MockTransport 接收 0 次。
- 直接证据：raw 记录 state=not_dispatched，proof 为 admitted_http_attempts=0、reason_code=AUTHORIZED_TOKEN_BUDGET_REACHED；artifact 外层仅有 request_hash。同 operation 再调用却返回 ARTIFACT_TEXT_WORK_OUTCOME_UNRESOLVED。
- 根因：artifact 单独保存 request_hash/result，没有将外层 reservation 接到现有 parent_reservation/CAS 分类机制。底层分类正确，外层身份记录和重放判定没有同步。
- 影响：将确定的本地拒绝呈现成未决，阻塞该操作的准确诊断/受控恢复，可能使 Agent 错误理解可继续工作条件。
- 保全：0 HTTP、无 usage/ReviewRecord；重复不增加发送。发送后超时对照保留 unknown 及完整预算上界，不能为修零发送而释放真实未知。
- 阻挡动作：阻挡 artifact 本地拒绝生命周期宣称通过；不阻挡本次非 artifact 的四个独立合成探针。未证明历史付费运行曾触发，也未证明数据损坏。
- 回归：tests/test_artifact_io_lifecycle.py::test_artifact_replay_preserves_actual_dispatch_classification[zero-dispatch] 保留红；对应 [dispatched-timeout] 绿。

### NFR-10 — P2：工作摘要将本地准入拒绝统一记为未知

- 位置：src/report_agent/working_summary.py:118–122、147–153。
- 触发：真实 WorkingSummary._acreate_summary 调 configured adapter，实际 hook 在发送前拒绝。
- 直接证据：AUTHORIZED_TOKEN_BUDGET_REACHED、admission proof 零发送、MockTransport 0 次、原 history 不变、无摘要/usage、无新增未知预留；但 failure record.reason=SUMMARY_OUTCOME_UNKNOWN。再次调用被 SUMMARY_POLICY_REPAIR_REQUIRED 拦截。
- 根因：except BaseException 把所有模型调用失败归为 SUMMARY_OUTCOME_UNKNOWN，没有保留已证实的准入前拒绝。保护未知不重放的机制同时错误涵盖了已知未发送。
- 影响：错误的失败来源和 scope 级 repair block，妨碍预算条件变化后的有依据恢复；不代表摘要内容丢失。
- 保全：history 不变、无返回 summary、重复 0 新发送。发送后超时对照仍 unknown，10000 上界保留。测试外层 logical_request_admission 是旁观证明，不代表生产摘要当前已接该包装。
- 阻挡动作：阻挡工作摘要本地拒绝分类/恢复验收；不阻挡本次独立实模探针。无根据据此宣称全部摘要/取消路径都存在同一缺陷。
- 回归：tests/test_summary_io_lifecycle.py::test_summary_preserves_history_and_actual_outcome_classification[zero-dispatch] 保留红；对应 [dispatched-timeout] 绿。

两个问题不是此前“通用240字符裁剪仍存在”的证据。共同问题是调用层各自保存生命周期，却没有一致消费底层确定的发送事实。不能只凭异常名字或缺少 response 就将旧未知记录改为未发送。

## 四次真实合成探针：独立结论

唯一输出目录：.analysis/agent-io-regression-20261018/probe-live-v1。

| 探针 | 实际模型与公开返回 | Neo 判定 |
|---|---|---|
| Writer 单步 | glm-5.3，search_sources(query='class B', source_id='s') | 42 个完整公开工具重新绑定；参数合法，选择与“先检索指定资料”一致。未执行该动作，不证明后续选材/生成完成。 |
| Reviewer 单步 | deepseek-v4.1-flash，read_task_assignment({}) | 37 个完整公开工具重新绑定；参数合法，读取当前分派是合理起步。未进行 checker 调用或生成 ReviewRecord。 |
| 正常文字生产 | deepseek-v4.1-flash，payloads 中保留 75–100 原始陈述与来源、单位/表格不可核实的限定 | 真实 process_report_content 及 parser 接受；输入/原始返回/保存 payload 对齐。该 fixture 只有纯文本，无物理页表，不能据此宣称“正常表格材料”已测或过度谨慎已证产品缺陷。 |
| 缺料文字生产 | deepseek-v4.1-flash，明确所给资料缺表，不选数值/范围/分数，区分本次未提供与全源不存在 | 结构合规，合成缺料场景中没有编造；保留 partial coverage 和物理页未定位局限。只是一例，不证明长期抗幻觉能力。 |

逐项比对：Writer/Reviewer 捕获的两个原生消息正文与真实 wire 正文相同，工具名称集合/数量相同；两条文字工具 system 与完整 packet 字符串到 wire 相同，原始 payloads 与 parser 返回 payloads 相同；两条文字返回 finish_reason=stop。不是替换角色 prompt 的独立玩具 JSON 提示。

当前既有服务是百炼兼容 endpoint，strict=0 为原配置，不是为本轮降级。该结果不验证官方 DeepSeek beta strict 编译路径；UF-STRICT 等其他未闭合问题不因本次通过而关闭。Writer 的 max_completion_tokens 与 DeepSeek 的 max_tokens 在实际 wire 均为本次 8192；这是显式探针限制，不等于生产默认。

## 成本和数据边界

- 4 HTTP、4 responses、0 重试；actual usage 增加 46603 tokens（缓存包含在内，不另加）。
- 170000000 总授权不变；recorded_tokens 从 93328297 到 93374900。
- 既有 1028 条 attempt 原行不变；增加 4 条 settled；26000000 原未知/保留不释放，无新增 unknown。
- 新预留余量 50625100；该余额不表示自动批准下一波。
- 探针临时 workspace 与旧报告 case 隔离；未采用候选、未执行真实模型 tool_calls、未生成新报告或修改原报告数据。
- live 注册覆盖代码/prompt/helper/runner，during 核对为真；Neo 再查当时登记的 src 条目，当前无变化。随后新增 summary 测试不倒算为 live 运行时变更。

## 建议下一轮的最小修复边界（提案，不是本轮实施）

1. 先修 artifact 的确定发送事实在 outer/raw 两层间的保存与重放分类：以 artifact_review.py 为主要修改点，复用 evidence_analysis.py 的 parent_reservation 和 bounded_operations.py 的既有 CAS。外层目前没有 state，需明确新记录以及旧 request_hash-only 记录的兼容，不能直接套 API 而造成 KeyError/CAS 失败。不要新增通用调用框架。
2. 再修 working_summary.py：在真实 logical admission 作用域内保存有证明的未发送原因；对真正已发送超时、外部取消/无证明失败保持保守未知和历史保护。不要自动 rearm，不修改既有 unknown 记录，不增加第二份预算账本。
3. 两个修复分别用本次红例转绿，再跑现有 unknown/cancel/once/replay、摘要 history/namespace 隔离回归；无需再次付费来证明这些程序分支。若要允许“拒绝后如何恢复”的新行为，先单独说清权限、显式操作与旧状态兼容，不由测试顺手扩大。

仍暂停原 batch1 C1/任务上下文重构；本轮只保留/扩展验证。新增功能、真实角色多步行为、长资料/图表、实际 Word/Excel 和报告质量需另定范围，不以这四次调用代替。

## 主要证据指纹

相对项目根目录：

- .analysis/agent-io-regression-20261018/siblings-v2/result.json：baa06954a3886bd2773ba9e42729dea166a89e04ba751cdb9cf8991658aad31c
- .analysis/agent-io-regression-20261018/state-and-identity-v2/result.json：05a15689f5589b7913f1f978c52918857cb23eaedd4bf59dba0ff2799588a2d8
- .analysis/agent-io-regression-20261018/summary-lifecycle/result.json：6fd3696a44ad2a248e3a0366d3736bad46904257217f410a77212f5ac51a67e9
- .analysis/agent-io-regression-20261018/probe-live-v1/result.json：a2156ce1769baa4b9c1c6deb73dc52aff334c765ca060889088ff4506eef89d4
- scripts/probe_agent_io.py（实际 live 版本）：760b2cffd8367bca71bd3121c607ed7fbcfcea36250b76e2a2ee211fb1b8a585

原始 wire、model-output、native-input、文字工具 packet、ledger-before 和各次失败日志保留在上述运行目录。复核未读取或转述模型私有推理，判定依据为实际输入、公开内容、结构化调用、usage 与程序状态。
