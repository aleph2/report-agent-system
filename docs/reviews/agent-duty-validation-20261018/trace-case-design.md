# 从 trace 设计职责测试

用户本轮强调：测试用例的设计比增加严格程度更重要；可以从 trace 得到启发。Codex 实施，Neo 核查用例是否保留触发机制、预期是否来自需求，以及实际失败发生在哪一层。

现有绿例不能证明系统整体稳定。脚本预先给定正确动作时，能查程序是否损坏输入输出，不能说明模型会自主选对动作。单次结构合法也不能覆盖恢复、版本变化、部分完成和最终产物。测试数量不是职责覆盖率。

## 每个案例保留什么

记录六件事：原 trace/观察来源、触发前状态、关键输入与步骤、独立预期、实际消费方的观察点、最小对照。业务资料可替换为简单合成数据，但不能删除触发问题的版本、角色、范围、尾部限制或调用顺序。只固定必要条件；不要求模型重复历史工具顺序，多个合理动作都可接受。

## 已执行的案例与结果

| 案例 | Trace/机制来源与最小场景 | 预期及实际观察点 | 实际结果 |
|---|---|---|---|
| D-RESUME-01：恢复后的当前要求 | 初次 Layout 任务15mm；同 task、owner、snapshot grant 恢复，明确替换为20mm。Writer 的草稿→先调查作为相邻场景；managed开/关作对照。 | 新指令完整到达；原始任务允许留存，但不能仍以当前权威要求呈现已被替换的值。看实际子模型 System/Human，不能用测试另行读取的状态冒充已送达。 | managed=True 的 Layout System仍把15mm标为当前，同时Human为20mm。Neo确认P2输入当前性缺陷；managed=False未见该System冲突。未证明模型实际采用旧值。 |
| S-SOURCE-240：原文投影裁剪敏感性 | 历史240字符投影机制；用长合成原文与尾部限制。只在测试内存 public_value 恢复该错误，归档与owner/SHA保持。 | 原有未修改的下一模型输入断言必须发现原文变短，而非因导入、权限或平台合法offload失败。 | 原oracle准确在metadata.blocks[0].text与固定原文不等处失败。敏感性测试通过，不是当前产品新增bug。 |
| S-PRODUCER-LIMIT：工具限制说明遗漏敏感性 | 历史producer正文/控制信息分离机制；合成结果含未核实限制。仅公开映射丢qualifiers。 | 原有未修改的Writer输入断言必须发现限制说明消失；正文仍可通过原receipt延后读取。 | 原oracle准确在qualifiers与固定输入不等处失败。敏感性测试通过，不是当前产品新增bug。 |
| S-REUSE-EXTENT：旧局部完成被当新子树完成 | 保留已有真实保存/复用回归；先local_body审核，再请求subtree_bodies。同目标/标准/版本，仅范围不同。内存中仅移除范围相等比较，其他防线保持。 | 原oracle必须发现错误复用；若独立防线已拦住，则应记录其效果，不能算检测失败。 | 该单项故障确实导致新任务execution_complete=True，原oracle在期望False处失败。证明该保留案例能检测此类复发。 |
| L-LIVE：能力查询之后构造排版调用 | 当前真实合成trace：Layout已收到完整capabilities与snapshot，再调用真实GLM。 | 原样校验工具名/参数；核实际发送schema，不替模型修参数。 | 边距/行距正确，但qualifier_placement放错层级。当前schema与capability均有正确层级；验证器拒绝。模型本次构参失败，未证程序改写接口。 |
| C/E-LIVE：后继动作与审核结论 | Co收到partial；Optimizer读到before/evidence；checker面对70与75–100冲突。 | 合法结构与业务选择分开；纯文本合理等待不一律判错；收到但不完整不能记unknown。 | Optimizer下一动作结构合法，尚未执行。Co/checker均在探针8192输出上限处结束，无可判断动作/结论。不能算两个产品bug或行为通过。 |

D-RESUME-01 的源代码、四条输入对照与影响判定见 [Neo审查](neo-review.md)。它来自新增跨步骤诊断，不能倒推出历史R6报告就是同一原因。

历史版式trace还记录：Coordinator最初看到240字片段，但随后恢复过完整标准。因此“曾有裁剪”不能直接证明“永久没有收到边距标准”。本轮敏感性只复现投影缺陷机制，不伪造一条历史报告错误的因果链。参见 `../../../.analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/neo-trace-review.md`。

## 保留不成功的实验

首次在bound_result之后改显示文本，producer限制被现有最终交付机制从原档补回；source则转换为合法offload控制信息。它没有复现目标错误，所以该次两个敏感性用例的失败不能算两个产品bug，也不能证明原oracle无效。第二次改为内存公开映射处注入，保留全部独立防线，才使目标错误到达实际模型输入。两轮结果与源码hash均保留。

学习测试初轮使用了错误fixture字段（category而非kind、candidate_id而非experience_id），已按实际注册schema纠正；原失败保留，不计产品缺陷。没有修改原oracle使错误输出变成合法。

## 可重复证据

- `tests/test_agent_duty_handoffs.py`：显式交接、完整选材、恢复诊断及三个敏感性案例。
- `tests/test_agent_duty_learning.py`：独立分析/候选/处置；两条反馈只处置一条后，流畅“Done”不能把job标完成。
- `tests/test_agent_duty_artifacts.py`：固定排版参数经过真实导出后核DOCX结构，不从当前默认值反算期望。
- `../../../.analysis/agent-duty-validation-20261018/resume-and-sensitivity/`：恢复对照及首敏感性实验。
- `../../../.analysis/agent-duty-validation-20261018/sensitivity-public-projection/`、`sensitivity-completion-reuse/`：准确失败断言与故障后的实际输入/结果。
- `../../../.analysis/agent-duty-validation-20261018/roles-live-wave1/`：4次真实调用，86,705 recorded tokens，旧26m未知占额保留；无自动补跑。

这里的“敏感性通过”表示内存植入错误后，原回归确实失败。它不表示业务正确率，也不是增加三个真实产品bug。44项职责仍逐项在 [coverage.json](coverage.json) 区分程序证据、真实模型证据与产物证据。


## 2026-10-19 当前证据更新

上表是首波时的状态；后续证据如下，原始调用和失败仍保留。

- `contract-live-wave2`：Co选择不存在于其状态的assignment路径；实际原生离线重放将STATE_PATH_NOT_FOUND送回模型，fake明确选择有效review_tasks路径后继续。真实模型没有自主恢复证据。独立checker在配置容量下返回并保存合成70对75–100的not_satisfied；简单原表复制和qualifiers-only也通过实际解析，原报告未采用。
- `test_agent_duty_trace_cases.py`：实际typed Criterion缺字段/错误Ref的原子拒绝、Writer结构与实质内容的权限边界、合法Evidence源版本池与缺池零调用、E7缺依赖的失败保存与重放拒绝。失败要区分产品缺陷和夹具取错表示。
- `test_agent_duty_visual.py`：Reviewer/Layout的实际源物理页和实际Word渲染图像交付；full/crop/cache/越界；Layout明确调整后的新文件与新render绑定，旧render可读取但不能冒充新版。独立视觉模型响应是fake，未证明视觉判断正确。
- `retained-trace-final`的73个定向测试与`native-layout-adjustment`的1个补充测试均通过；包括已有回归复跑与已知缺陷诊断。不能称74个新发现案例或全职责覆盖。
- 当前43项职责各有明确有限程序切面；E7正向GEPA仍因缺dspy未验证。全部职责的广泛组合/真实决策/完整客户产物仍不满足全覆盖声明。最新逐项状态以Neo维护的coverage.json为准。
- 新增`test_probe_output_limit.py`保留本次测试脚本默认覆盖配置的反例，分别观察Agent与独立文字工具最终HTTP参数。它验证测量工具的忠实性，不代表应用功能增加。

本阶段付费仍为8次收到响应，148,507 tokens，新增unknown为0；57,399为输出容量受限而没有公开职责结果的测量成本。历史26m未知占额不释放。已确认D-RESUME-01仍未修复。
