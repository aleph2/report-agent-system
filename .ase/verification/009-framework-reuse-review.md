# Task009 Framework Reuse Review

日期：2026-09-28。审查对象：新仓库当前源码，不是旧项目，也不是 Task009 报告内容质量。

执行者：当前 Codex 审查会话，独立于 Main 本轮运行与实现决策。独立性限制：本会话此前参与过 Knowledge/embeddings、文档工具及 error_data 的实现；这些部分不能称为完全独立的作者外验收。本次用安装源码和离线故障注入核对边界，不以历史实现者的说明代替证据。Main 的取舍尚未写入本报告。

范围：只读程序、框架源码和已有测试定义；只新增本报告。未改代码/配置，未运行 CLI 历史入口，未读写 Task009 项目数据库、图谱或 checkpoint，未触发真实模型、网络或 deployment。内存探针使用 Python `-B`、内存 Store/checkpointer 和 scripted model，不在仓库生成测试文件。生命周期：当前真实主干运行的架构旁路审查，不是新验收门禁。

## 结论

**不能支持“当前系统大量重造 DeepAgents 框架”的判断；能确认一处不合理的额外执行控制，以及一处历史入口维护冗余。**

- P2：BusinessBoundary 按相同调用签名三次硬失败，未观察 handler 返回值，误停有新观察的调用，也能先于业务 receipt 拦截重放。
- P3：公共 CLI 仍暴露历史 ADK `run` 路径，但依赖已仅列为 `historical-tests`。这是仍可达的第二套历史运行栈，不是 Task009 当前调用链中的重复执行。
- 原生模型/工具循环、子智能体、摘要、工具调用修补、todo、文件状态、checkpoint、interrupt/resume 已实际接入。主路径重试来自 OpenAI SDK，没有发现应用层再套一次当前模型/整任务重试。
- 自写事务 receipt、来源版本、生产者权限、观察/采纳关系、graph、导出及图像访问主要属于应用语义，不能因代码多就删，也不能假定框架自动实现业务幂等。
- **排除“Knowledge 构造导致 Neo4j/embedding 成为无图任务启动依赖”这一疑点。** 构造是惰性的；已有成果实际采用 graph facts 时的核验依赖应保留。

## 安装版本与证据范围

WSL Ubuntu-24.04，`/home/dysun/.venvs/report-agent-system/bin/python` 的 distribution metadata 实测：

| 包 | 已安装版本 |
| --- | --- |
| deepagents | 0.7.19 |
| langgraph | 1.2.12 |
| langchain | 1.4.2 |
| langgraph-checkpoint-sqlite | 3.1.1 |
| langchain-openai | 1.6.6 |
| openai | 2.54.0 |

下文框架路径均相对于 `/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/`，程序路径相对于 `C:/Users/dongy/Documents/ChatGPT/report-agent-system/`。行号来自此次实际文件，非宣传文档或旧评审的推测。安装源码足以回答本次问题，未额外依赖不同版本的在线文档。

## 确证问题

### FR-01 / P2：结果无关的重复调用门槛会误停原生执行

- 位置：[deep_runtime.py:59](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/deep_runtime.py:59)、[deep_runtime.py:65](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/deep_runtime.py:65)。计数只看工具名、参数、SQL result IDs、context_revision；第三次在 handler 前抛 `REPEATED_ACTION_WITHOUT_PROGRESS`。
- 实际影响：即使前两次工具返回不同图版本/观察，第三次也不执行；错误不是给 agent 的普通业务反馈，而是上抛至 [run_report 的失败处理:445](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/deep_runtime.py:445)，可终止当前运行。该计数也不持久化，重建 agent 后重新计数，不能当可靠的无进展判据。
- Receipt 边界：[submit_result:227](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/deep_runtime.py:227) 内部确实先查原始请求 receipt，但外层 middleware 先运行。已经提交成功的请求可以在进入 receipt 查询之前被 gate 挡住。
- 离线实测：同参 handler 返回 `revision=1`、`revision=2` 后，第三次得到 `REPEATED_ACTION_WITHOUT_PROGRESS`，handler_calls=2。实际 `submit_result` 的既有 receipt 连续返回 `saved`、`saved` 后第三次被挡，receipt 查询仅两次；重建 BusinessBoundary 后再次返回 `saved`。
- 严重性依据：局部可靠性错误，可使单次运行误停；未证明数据损坏，也未证明 Task009 已触发。不是 P1，更不能据此声称当前运行的模型挂起已找到原因。
- 最小删减：删除 `last_action/repeat` 和签名计数硬失败分支；保留串行锁、安全错误转换、事件及业务 receipt。不要另造语义进展分类器、固定任务额度或新门禁替代。原生 recursion_limit 也不是语义无进展检测器。
- 处置：Main 在当前冻结运行结束后处理；不要求中断、重启或热改 Task009。阻断的是“该 gate 可可靠保护恢复/进展”的正确性声明，不阻断继续观察隔离主干。完整 checkpoint 多次 replay 路径本次未重现，不能把同实例重放结论扩大为“所有恢复都会被挡”。

### FR-02 / P3：历史 ADK 入口仍暴露在当前公共 CLI

- 位置：[cli.py:13](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/cli.py:13)、[cli.py:62](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/cli.py:62)。`run` 仍导入历史 `runtime.run_task`；`report-run` 则在 [cli.py:46](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/cli.py:46) 导入 `deep_runtime.run_report`，Web 也在 `webapp.py:17` 使用后者。
- 重复职责证据：`runtime.py:53` 的整任务 timeout、`:62` 的 ADK Runner；`models.py:32` 的自写三次尝试及 `:62` 的旧超时配置；`report_runtime.py:225` 的任务恢复/执行、`:273` 的自写委派封装、`:300` 的另一套 report runner。它们是历史原型实现，不是当前 DeepAgents 外层又跑了一遍这些逻辑。
- [pyproject.toml:13](C:/Users/dongy/Documents/ChatGPT/report-agent-system/pyproject.toml:13) 把 ADK/LiteLLM 放在 optional `historical-tests`，不应宣称当前核心依赖仍强制安装 ADK。保留公共 `run` 却仍要求这一 optional 栈，带来入口含义、错误呈现、超时/重试文档和测试维护的分叉；最小依赖安装不能据此保证该历史命令可用。本次没有执行它。
- 严重性依据：维护/入口清晰度问题；当前 Task009 主调用链不受其额外模型调用或旧 deadline 影响，因此 P3，不是当前运行故障。
- 最小删减：后续移除公共 `run` 的历史 dispatch，或明确迁至历史测试入口；保留已有历史证据和仍有价值的 fixtures。不要立即删掉被旧测试直接引用的领域 helpers，更不要删除旧项目或其数据。
- 处置：Main 后续清理；不阻断当前实验或报告草稿。不能用“仓库存在旧重试代码”推断当前 SDK 重试发生叠加。

## 逐项职责映射

| 范围 | 当前实际实现与本机框架依据 | 判断 / 最小化边界 |
| --- | --- | --- |
| Control / agent loop | `deep_runtime.py:375` 调用 create_deep_agent；`deepagents/graph.py:961` 调用原生 create_agent。当前 run_report 只选择新输入、继续或 resume，之后一次 ainvoke。 | 已复用；没有自写 token/tool 循环。FR-01 是额外且有害的控制，不代表整个 adapter 都应删除。 |
| 子智能体 | `deep_runtime.py:369` 声明角色/model/tools/middleware；`deepagents/middleware/subagents.py:600` 编译 create_agent，`:801` 构造隔离消息上下文，`:854` 继承父 config，`:863` 执行原生 ainvoke。 | 已复用；没有当前自写子任务 scheduler。角色对应能力/权限，不等于要求每个角色必跑。关闭 general-purpose 子代理是权限配置，不是重造委派。 |
| Middleware / context | `deepagents/graph.py:867` 文件系统、`:876` SubAgentMiddleware、`:890` summarization、`:891` PatchToolCalls；自定义 stack 在 `:931` 合并。 | 应用没有重造摘要/工具调用修补。文件系统覆盖配置不是重复安装，见同文件 `:205` 按 name 替换。 |
| Todo | `deep_runtime.py:378` 直接加原生 TodoListMiddleware；`langchain/agents/middleware/todo.py:150` 的 write_todos 返回 Command 更新 todos，`:201` 声明 state_schema。 | 原生工作笔记。Workspace 的不可变成果和提交记录不是 todo 的第二套权威实现，不能把两者混为一谈。 |
| File | `deep_runtime.py:364` 用 StateBackend，`:367` 配置六个原生工具。`deepagents/backends/state.py:81` 读 files channel，`:99` 通过原生 channel 写入。 | 原生 scratch 文件随 graph state 管理；不是模型任意读写真实项目文件。原件、导出物的受限访问不是重复 scratch backend。 |
| Retry | `deep_models.py:100` ChatOpenAI max_retries=2；`:112` vision SDK 同配置。`langchain_openai/chat_models/base.py:1470` 传入 SDK 参数，`:1540` 构造 AsyncOpenAI；`openai/_base_client.py:1686` 执行 SDK 尝试循环。 | 当前不是自写 retry engine。`langgraph/pregel/main.py:742` 默认空 retry_policy，`_retry.py:799` 无 policy 即上抛；编译探针也确认空 policies。不得删除 SDK 重试后再增加新外层重试。Neo4j execute_write 的事务重试是另一资源的驱动语义，不是模型重试叠加。 |
| Checkpoint / recovery | `deep_runtime.py:385` 原生 AsyncSqliteSaver；`:409` aget_state；`:421` Command(resume)；`:423` payload=None；`:428` ainvoke。`langgraph/checkpoint/sqlite/aio.py:321` 原生 checkpoint_ns 主键，`:509` aput、`:561` aput_writes。 | 已复用持久执行，未自造 checkpoint serializer。thread/project 绑定、operator decision 与 interrupt ID 的对应是必要 adapter。 |
| HITL | `deep_runtime.py:279` 的 ask_human 调用原生 interrupt；`langgraph/types.py:890` 定义中断，`:902` 明确恢复会重执行节点。原生 graph.py:922 仅有 interrupt_on/permissions 时装审批 middleware。 | 当前使用 native interrupt，不是 HumanInTheLoopMiddleware 的工具审批配置；二者不能混称。领域 issue/人类决策去重必须保留，checkpoint 不自动保证业务 write-once。 |
| 串行化 / process lock | `deep_runtime.py:58` asyncio.Lock 串行工具和委派；`store.py:50` flock 保证当前 CLI/Web 同项目互斥。原生异步 ToolNode `langgraph/prebuilt/tool_node.py:858` 使用 asyncio.gather。 | 必要的薄并发适配。模型 parallel_tool_calls=False 是请求选项，不是服务端并发锁。不能把 checkpointer 的内部锁或 thread_id 当项目 writer 排他保证，也不建议限制 checkpoint executor 的并发来代替业务串行化。 |
| Web lifecycle | `webapp.py:103` run_guarded，`:124` create_task；停止 Web 时取消当前 worker，并在 status 中投影 worker 状态。 | 运行宿主管理，不是第二个 agent scheduler；没有后台轮询自动启动下一任务。 |
| 观察 / 权限 | `deep_runtime.py:110` 以 role+原生 checkpoint namespace 记观察；`workspace.py:290` record_read 与 `:384` 精确 draft 观察校验。 | “观察过某版本”与“采用某版本”的领域规则不由消息历史自动提供。可用自定义原生 state channel 存储，但不是删除即等价；本次无证据要求改写。 |
| 业务 persistence | `workspace.py:263` 明确 request_task 只绑定 producer/inputs/receipt，不调度；`:315` BEGIN IMMEDIATE，`:401` 保存成果、`:422` 更新提交记录；`knowledge.py:173` 图事务 receipt；`store.py:171` analyses cache。 | 业务权威与框架恢复状态不同。框架 checkpointer/cache 不能直接替代跨调用的不可变成果、事务 receipt、版本采用、生产者权限或图关系。 |
| Audit | `deep_models.py:69` 继承原生 BaseCallbackHandler；工具边界写少量事件。 | 用的是原生回调，不是新的 callback dispatch 框架；本地事件持久化及对 GUI 的安全过滤属于 adapter。全量 prompt 留存的重复另见下节。 |

编译探针直接运行当前 build_agent，使用报告 provider=openai 的 scripted model、内存 checkpointer；仅捕获编译参数，未运行模型。Coordinator 实际 stack 为 FilesystemMiddleware、SubAgentMiddleware、SummarizationMiddleware、PatchToolCallsMiddleware、BusinessBoundary、TodoListMiddleware、AnthropicPromptCachingMiddleware、UnsupportedContentMiddleware；子代理具有文件系统、摘要、修补和 BusinessBoundary 等原生 stack。所有捕获的编译图 retry_policy_count=0。native 编译内部可能多次构建子图，不能把工厂构建次数当模型调用次数。

当前没有配置 SkillsMiddleware、MemoryMiddleware、工具审批 interrupt_on 或远程 AsyncSubAgentMiddleware。这些是未启用能力，不应凭框架宣传声称已经使用，也不是本次发现的缺陷。

## 可以简化，但不能据此认定运行故障

### 错误转换：原生支持存在，应用语义仍需保留

`deep_runtime.py:76` 的捕获 ActionRejected/ActionForbidden 并构造 error ToolMessage，与 [本机 ToolErrorMiddleware:190](//wsl.localhost/Ubuntu-24.04/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/langchain/agents/middleware/tool_error.py:190) 提供的包装机制重叠。后者在 `:192` 保留 GraphBubbleUp、`:197` 调用户 callback、`:204` 构造 error ToolMessage。

可直接复用其 callback，继续使用安全 error_data 和本地业务审计；但现有重复只是一小段包装，串行锁/审计仍需存在。**没有证据表明为了这几行再加 middleware 会净减少复杂度；不是必须整改或新增门禁。** 不得把所有异常都吞成业务拒绝，也不得吞掉原生中断。

### Audit：重复留存成立，不等于业务控制过多

`deep_models.py:78` 每次保存完整请求 messages，`:85` 保存完整 response generations；`store.py:181` 将事件存入业务 SQLite。重复前缀确实重复保存：内存探针输入依次包含 1、2、3 条消息，3 条不同消息产生 6 份持久化消息副本。无摘要时，这类增长前缀具有累积复制成本。

但有效 system prompt/middleware 注入、独立 text tool 的实际输入，并不保证能从最终 checkpoint 完整反推；本任务还明确要求真实调用证据。因此不能直接删除 LocalAudit，或声称框架事件流已自动代为持久化这些证据。当前只确证额外序列化/留存，未测量 Task009 的磁盘、时延或性能损害，不升级为确定性能 bug。

最小可选优化是未来精简重复 event payload，保留 run_id、role、usage、错误和已有 message/checkpoint 引用；需要完整有效请求取证的场景继续保留实际 payload。不要为此开发另一套 checkpoint、日志合并或工作流引擎；本轮 Task009 冻结证据保持原样。

### 状态投影不是当然有害，也不要升级为第二权威

`checkpoint_resume`、`native_interrupts`、agent_summary 在 `deep_runtime.py:410/430/431/438` 和 `webapp.py:93` 用于 UI 投影。恢复主体仍读取原生 snapshot，而不是重新解释一份自建 checkpoint。

`deep_runtime.py:393` 的 reviewed_draft 快速返回先看 SQL checkpoint_resume，再读原生状态；这提示未来应避免让投影替代原生执行事实。但本次未证明当前受支持流程能产生相应不一致，故不列为确证 bug，不提出为未证实风险新增状态机。

## Graph 启动依赖专项核验

1. `deep_runtime.py:407` 确实在默认生产分支实例化 Knowledge 并写入项目 graph 身份。
2. [knowledge.py:63](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/knowledge.py:63) 只设字段；`_driver=None`。`:76` 的 driver property 才创建驱动，`:95` 的 _schema 才执行 schema/索引语句。构造不校验连接、不调用 _schema。
3. [embeddings.py:51](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/embeddings.py:51) 构造只计算 cache path；`:56` embed_documents 才调用 _load，下载/ONNX 初始化在 `:21` 的 _load 内发生。
4. `knowledge_state.py:9` 未采用 fact IDs 时直接返回 not_used，不创建图访问；已有采用关系时才 read_many，核验失败标 unknown/system_error，而非把图事实无声当作有效。
5. 内存隔离实测保留 `run_report(model_factory=None, knowledge=None)` 的生产条件，实际创建 Knowledge；只将 configured_model 换成 scripted model、SQLite saver 换成 InMemorySaver、业务存储/目录换成内存替身。把 GraphDatabase.driver 和 embeddings._load 都设为“一调用就 AssertionError”。实际 native graph 完成 1 次 scripted coordinator 调用；graph_driver_calls=0，embedding_load_calls=0，knowledge_project_bound=true，最后 needs_attention（无草稿提交，不声称报告完成）。Knowledge.describe/close 同样未触发这两个钩子。

**判定：该疑点在当前实现中不成立，不列 P2/P3。** Python 模块导入和轻量对象构造仍是启动代码的一部分，但不是 Neo4j 服务/embedding 模型可用性依赖。不能把采用已有 fact 的真实性核验删掉来伪造“无图可运行”。首个真正 graph 操作的故障呈现和降级体验不属于本次启动探针所证明的内容。

## 验证摘要与未验证项

| 验证 | 实际结果 |
| --- | --- |
| 安装版本、本机框架源码 | 已核对上述精确版本和行号。 |
| 当前 build_agent 原生编译 | 已核对 middleware stack，retry_policy_count=0；没有真实模型调用。 |
| 相同参数、不同观察 | 两次不同返回后，第三次 handler 前失败；FR-01 确证。 |
| 当前 submit_result receipt | 两次返回既有 receipt，第三次 gate 先挡；重建边界后可恢复。完整多轮 checkpoint replay 未实测。 |
| Neo4j/embedding 惰性 | 禁止连接/加载的故障钩子调用均为 0，无图 native 调用可启动并结束。 |
| Audit 重复留存 | 3 条不同消息、3 次增长前缀请求，存 6 份消息副本；没有生产性能归因。 |
| Task009 真实运行、当前数据库、模型判断质量 | 未检查、未改变；不推断其是否触发 FR-01 或是否已有合格报告。 |

本轮不建议替换框架、新增专家/审查 agent、工作流阶段、调用额度或运行门禁。最有价值的删减是 FR-01 的硬失败分支；历史入口清理和审计精简按收益安排。领域 source/graph/export、资源上限、来源权限和写入 receipt 不在“因为框架已支持所以可删”的清单中。

## 源码快照

审查时 SHA256，便于 Main 判断后续代码变化是否使行号/结论失效：

```text
src/report_agent/deep_runtime.py FBA17C7BC94D06E46E019644BEE808BD7CE5680BE8B222539A9466D55E5633FE
src/report_agent/deep_models.py 98C0B0057B4A98158D508B0BB9BD4DFAC8A8808F2A3148D3ADC0EB05357C6C41
src/report_agent/knowledge.py 35376D7F832B81704028BF864ADBE98A96520FF74F90216BF37687C56D1C1410
src/report_agent/embeddings.py DF679D6E5574F54088257ED31223A20268D32184F6A91CAB10574396353E3096
src/report_agent/cli.py AC7EDA9FC29261CC346A9E72DF51F7C8CAE4C1F6389BCCFBF6B4B748491C0522
pyproject.toml 7938F8DF06800221685AAC57993C8F0C38567F12BDDD2F930CD19A91D4830B7C
```
