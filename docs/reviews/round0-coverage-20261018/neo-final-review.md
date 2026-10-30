# 第0轮：Neo审核与下一步建议

状态：**本轮限定范围的结构覆盖基线审核完成**。本文件不宣称测试已全部通过、系统MC/DC达标或报告已验收。Neo只读源码与测试、审核诊断代码及结果；Main执行。此轮未修改应用、既有测试oracle或预算，未调用provider。

## 实际结果与审核结论

基准HEAD `896c9975cac648e7cd5636e4ef6b38d5e71b459f`。已对账Main保存的原始reports、coverage和汇总：

|项目|本次证据|限定|
|---|---|---|
|Python测试|1868个已收集唯一nodeid：1726通过、112 call失败、21 setup错误、9 setup跳过|另有2个模块因缺gepa/dspy在collection跳过；不能把pytest摘要11 skips全部当已收集case。无collection error、无已收集未运行case。|
|行覆盖|11066/12710，87.0653%|93个Python源文件的可执行statement分母，不是物理行或需求覆盖。|
|分支覆盖|4050/5048，80.2298%|包含当前全部src分母；不是条件覆盖或MC/DC。没有为了抬高比例去除历史路径。|
|旁观对照|同1868 nodeid终态完全一致，0差异|证明这组测试的结果未被探针改变，不证明所有adapter均被捕获。baseline源hash无变化；observed仅独立inventory诊断代码变化，src/tests/pyproject稳定。|
|原生接口|六配置的18个role/profile最终绑定表面完整；173个role/name union，其中45个在BusinessBoundary有尝试记录|不把45/173报成接口覆盖率。110个BaseTool入口未归属角色，保留；compiled路由与模型可见schema不同。|
|关键路径|24协议族的候选参数实例均在本次通过|仅证明这些样例；状态组合、边界循环和异常阶段还未完整映射，不能报关键路径100%。|
|独立条件|C03、C08、C18的6个主对照nodeid在两次运行中均通过；各组仍缺条件|真实用例+源码/oracle核对，未插桩记录每次条件值。其余15组未独立审计；全系统MC/DC百分比unknown。|
|前端|现有静态DOM VM测试19/19通过|不是浏览器验收。V8的100%覆盖仅测试harness，app.js覆盖未测，learning.js未加载。|

完整证据入口为`metrics.json`、`file-coverage.json/csv`、`interface-matrix.json`、`path-matrix.json`、`failures-and-skips.md`；条件对照、精确源码位置/哈希和主对照运行phase记录在`neo-scope-review.json`。这些文件证明基线可供比较，**不构成所有I/O/权限条件充分覆盖或真实报告完成的结论**。

## 代表失败的归类

本次133个失败阶段不能当成133个独立产品bug。Main按直接异常链归类113个历史执行入口拒绝，余20阶段仍需逐项定位；Neo本次只核查以下代表项，不宣称剩余项已全部判明。

|失败证据|判断/严重度|影响与处置边界|
|---|---|---|
|`test_generation_records.py:146`调用另一测试缺少`reference_delivery`参数|P2测试复用接口漂移；测试未到目标业务路径|阻止该enveloped批量导出用例作为证据。修测试调用并保留其原业务断言，不能据此改应用。|
|`test_generation_records.py:87`仍要求generation_record派生摘要、<10000字且不显示长诊断；`test_object_index.py:132`要求旧object_metadata_tool等摘要|P2旧oracle尚未迁移到已确认的新公共契约|当前`decision_data.public_value:46`保留generation_notes，business envelope原样保留；不能为修绿恢复裁剪。保留原始失败并改为实际控制信息/完整原件恢复的断言。|
|`test_text_work_candidate_inputs.py:146`把`text_work.MAX_EVIDENCE_CHARACTERS`改为20但没有拒绝|P2失效探针，不证明真正阈值漏检|`text_work.prepare_material:206`调用PreparedMaterial方法，方法读`prepared_material.py:32`所在模块的常量。改导入别名不改变实际阈值；需测真正边界及0派发，不能恢复重复size判断。|
|`test_deepseek_strict.py:107`编译当前commit_objects schema遇allOf拒绝|**P2适配兼容缺口：本轮确认原UF-STRICT候选成立，非仅旧fixture**|最终Coordinator schema四配置均含allOf；`deepseek_strict.py:103`不支持该关键字；`deep_models.py:166`后真实strict请求会编译全部tool schema。因此只要请求提供该schema，deepseek_strict配置就在派发前受阻，并非等模型选择commit才出错。不阻止当前非strict GLM路径；不能通过去除业务校验或静默降级修复。|
|`test_vision.py:139`断言max_retries=0，实际为5|环境/fixture隔离缺口，尚未证为产品缺陷；P2测试证据债|`configured_vision_client`使用`sdk_retry_count()`，读取REPORT_SDK_RETRIES；此测试未固定该变量。客户端构造值不能证明发生过5次实际请求，也不证明越权重试。应明确覆盖0及合法显式配置，不能为修测试强改产品为0。|

历史入口被明确拒绝是有效保护；对应旧fixture需迁移到当前入口或明确验证拒绝，不能重新开放已退役模式。其它如clean_trial014、typed search错误后的KeyError等仍未在本审查中定因，保留未定；不按后继KeyError直接判资料检索损坏。

## 本轮最小可交付结果

1. 完整现有tests的真实收集、通过、失败、跳过及错误，绑定HEAD、源码和实际执行脚本版本。失败case数量不是bug数量。
2. 六种有限配置的最终model schema与compiled ToolNode路由表分列；按profile/role/stage/schema去重。分别报告提供、尝试、业务handler证据、结果断言。未知不要并入通过分子。
3. 24类关键协议路径对到精确nodeid、运行结果及实际断言；路径族中部分样例通过不能叫完整状态路径覆盖。
4. 三组复合判断的独立对照审核：C03身份、C08修订type/count、C18经验active版本；其余仍unknown。coverage.py行/分支不是MC/DC，这三组也均有明确缺项。

正常CLI/UI、decision_only等权限配置、隐藏注册路由及非ScriptedChat适配器不因六配置inventory而自动覆盖。原始两次inventory夹具失败保留；第三次正常task绑定+bind sentinel的结果是接口表面证据，不是Agent业务行为通过。

## 下一轮优先级与最小变更边界（建议，尚未实施）

### R0-G01：普通入口预算保护缺口，P1验证优先级

已有`test_token_budget.py`验证ledger及SDK hooks，但显式由测试包裹`with token_budget(...)`。当前`cli.py:68`、`webapp.py:161`直接进入`run_report`；`token_budget`未绑定时reserve可直接返回。辅助付费harness曾绑定预算，不等于普通入口已绑定。这里首先是入口保护的证据/契约缺口，不据此推定历史超支或所有入口都绕过授权。

先只增加测试：复用`test_token_budget.py`、`test_operator_instructions.py`及现有web入口fixture，临时case、合成凭据、正常configured adapter与MockTransport，观察真实正常入口的第一次请求。核对host已登记额度如何进入执行上下文、超额是否在发送前拒绝、成功usage是否精确结算、unknown是否保留。不能在测试外手工绑定预算再宣称入口负责；fake model_factory也不能代替正常adapter工厂证据。若入口没有配置授权policy的机制，先说明这个设计缺口及用户/host如何选择policy，不能擅自编一个默认额度。

涉及审查位置：`cli.py`、`webapp.py`、`deep_runtime.py`、`deep_models.py`、`request_budget.py`、`token_budget.py`。测试证明缺口后才提最小修复边界。本项阻止“普通入口已受累计预算保护”的声明及依赖该声明的新付费执行；不阻止当前离线基线和其它无付费工作。

### R0-G02：unknown与本地拒绝的兄弟生命周期，P2

文本生产已有0派发恢复测试，不代表artifact checker和WorkingSummary路径相同。当前`artifact_review.py`先存自己的请求占位再调用独立分析；`working_summary.py:149`后广泛异常分支把异常标成UNKNOWN。应复用`test_bounded_artifact_text_work.py`、`test_glm_native_summary.py`、`test_summary_context_provenance.py`、`test_not_dispatched_recovery.py`的真实程序路径，分别模拟：本地0派发拒绝、已派发无完整返回、收到后解析失败、收到后保存失败、同ID再次访问及明确新操作。

断言原始原因、确定性、linked reservation和已收到内容不被改写；收到后不得重发；未知不得靠新prompt/新operation ID重放。先明确哪一个共享生命周期负责每个状态，不能为每个工具另加补偿循环。涉及`bounded_operations.py`、`request_budget.py`、`evidence_analysis.py`、`artifact_review.py`、`working_summary.py`；此轮只建议补反例。阻止声称兄弟路径已安全恢复，或对不明结果作自动重试；不阻止记录unknown后停止受影响操作。

### R0-G03：公共I/O端到端契约的参数/状态缺口，P2

以最终inventory为分母扩现有`test_boundary_refactor.py`、`test_evidence_interface.py`和相应source/material测试。先覆盖代表性的成功、typed拒绝、缺料、冲突、平台offload：真实注册schema→实际工具实参/选材→校验与归档→返回包装→下一次模型输入/serializer→保存对象。普通大正文可按明确路径递延；缺料、限制和失败不能丢失；原文恢复入口和owner/SHA保持。不重新引入通用递归裁剪，不让测试中的Agent自动补救掩盖程序错误。

程序负责结构、权限、版本及真实选入范围；语义完成不能由字段齐全、自报completed或hash代替。测试只扩现有契约fixture，不建注册平台或另一套agent loop。阻止“所有公开接口/关键I/O条件已覆盖”的声明，不意味着尚未覆盖的工具已证有缺陷。

### R0-G04：三个已定位判断的独立条件缺口，P2测量缺口

- C03补tool、status单独变化；有效基线与拒绝应由同一构造器产生，尽量断言精确失败code。owner存在后续重复保护，不能强求删除一个等效guard的mutant一定失败。
- C08补单独object_type不符、count仍相符，保留现有count不符反例及0模型调用断言。
- C18补可访问但从未release的候选直接use；与release(NULL)分开，后者有行、只是active version不符。

涉及现有`test_boundary_refactor.py`、`test_text_work_scoped_revision.py`、`test_learning.py`；第一步不需修改应用。断言前提/条件值/决策结果后，才按具体方法报告局部MC/DC证据，不能转成整个系统百分比。

## 收束原则

先交真实基线，再选择最有价值的红例；Main说明每批改动的代码、责任和验证，Neo审核。95%普通代码分支目标不覆盖任一关键缺口。离线结构测试可证明确定性程序契约及反例修复；不会证明真实模型始终正确选材、表格/评分语义正确或最终完整报告已验收。
