# 第0轮覆盖基线：Neo范围审核

本文件保留初始只读库存与测量口径，并已补入本次执行对账。Main测量；Neo审核分母、关键边界及证据解释。本轮不改应用、不调用模型、不打开真实case数据库、不恢复迁移。

## 测量口径

1. 接口分母取实际native注册并最终绑定给模型的schema。报告角色为coordinator/writer/reviewer/layout；experience_optimizer单列；text_tool是独立LLM服务，不算第五个报告决策Agent。包含框架filesystem/todo/task/trace工具，不能只数business_tools函数。Host CLI/UI/operator API单列。
2. 每接口分别记schema提供、尝试调用、实际进入handler、结果/副作用被断言。合法配置、角色权限及参数等价类单列，不要求不可行的完整笛卡尔积。
3. JSON库存列24类关键协议路径及18组关键复合判断，作为首批明确范围，不冒充全src所有条件。Main仍应报告完整src statement/branch基线；活跃与退役路径另作解释，不为提高数字静默omit/deselect。
4. coverage.py只测行/分支弧。MC/DC须有同一决策的可行正反对照：保持其他逻辑条件，独立改变目标条件并改变决策结果。短路、顺序guard、循环/comprehension的约束须保留；多个错误同时触发不算独立影响。没有证据填unknown，不能填0%或100%。
5. 路径不追求数学上的全部组合。对列明协议及状态转移计数，循环按0/1/边界/超界；handler前、provider前、派发后、收到返回后、保存/恢复分别覆盖。

## 最小足够方法

先运行现有tests并保留失败；使用隔离安装的coverage工具、pytest临时store、fake模型和HTTP MockTransport，真实网络硬禁。只做日志/分母采集，不改产品逻辑，不为本轮覆盖修绿fixture。运行nodeid及参数实例与源码hash绑定。

Fake注入绕过工厂时，不能证明configured_model、SDK、HTTP hooks与序列化正常；该层需用真实配置构造加MockTransport。ToolNode/中间件/最终模型消息与实际保存结果同时核对，不能仅靠底层函数调用。

首轮不要求AST插桩：先作源代码/测试静态映射与实际执行基线。确有无法测量的独立条件时，再单独说明探针位置和验证，比较未插桩与插桩结果；不得宣称当前已测MC/DC。

## 当前明确缺口与限定

- 正常CLI/UI是否绑定持久全局token预算仍未证；hook存在不是入口绑定证据。
- text-work已知0派发测试不自动覆盖artifact checker与summary的兄弟生命周期；NFR05/NFR10仍单列。
- decision_data_delivered发生在平台offload前，不能代替最终有效输入或阅读凭据。
- learning.js反馈目标/证据刷新是JS交互问题，须独立DOM/VM证据，不纳入Python覆盖率后消失。
- schema provider能力及模型语义选择不是本轮零provider覆盖可证明的事项。
- 库存中的test node名称只是候选映射，不能将历史通过或名称命中改写为本次已执行证据。保留真实退役fixture失败；区分测试本身过时、当前程序缺陷和未定位失败。

本轮解释的机械目标：100%实际公开接口矩阵、100%列明关键协议/状态与可行独立条件是后续目标，不是当前已达。普通受影响代码95%分支是目标，不能用它掩盖任一关键遗漏；当前先测真实基线。

详细路径、条件组件及候选测试见同目录neo-scope-review.json。以上只是一份范围审核，不另建执行/审批框架。

## 测量脚本审核与证据边界

已逐行读取本轮`measure.py`。其隔离coverage安装、未观察/观察两次测量、保留真实失败与拒绝、源文件前后hash的方向合适。应用源码与测试当前已在HEAD `896c997`，不沿用此前未提交工作树的描述。以下是测量解释和收尾要求，不是新增产品缺陷或本轮修复授权。

- `BusinessBoundary`及`BaseTool.run/arun`入口记录只证明包装/调用入口被经过；后者先于参数校验，不能自动记成业务handler已执行，更不能记成结果已断言。两层记录不得重复累计成两次业务调用。
- schema须按实际角色、测试nodeid、有效配置、观测位置归属。`BusinessBoundary`下游工具集和特定`ScriptedChat.bind_tools`不是所有适配器最终wire的通用捕获器；未归属/未观察的组合保留unknown，不能用测试集合的union自证完整分母。
- 进程内socket guard不覆盖子进程。已读的`test_operator_instructions.initialize`仅调用临时case的CLI init，不是报告执行；仍需把其他子进程及可能的外部服务列为测量边界，不能将`provider_calls_allowed=false`这一策略字段当作所有进程零调用的实测证明。MockTransport正常保留。
- 哈希范围应包含诊断脚本及实际使用的JSON fixture；若主张静态前端接口覆盖，JS/HTML另列。不必为此重新哈希历史资料。未观察和观察pass需核对参数展开nodeid及结果，提前import与猴补丁造成的差异独立记录。
- coverage保存/报告失败时仍应独立执行observer恢复、源文件后核验与result落盘；不能让一次报告失败吞掉测量异常证据。

初始库存的18个判断均标unknown；本次收尾已给下述三组绑定真实通过用例，另外15组仍未独立审计，全系统MC/DC仍unknown。它也不是全部关键判断的最终分母：token-budget准入/结算、ContentStore提交/冻结等其它判断须随后补入或明确未覆盖，不能凭这18项声称系统条件100%。24个协议族也需要参数化成可执行状态转移后才能计算覆盖率。Neo没有新增或独立执行任何测试。

## 第二次审核：原生分母与三个条件对照

原始`interface-inventory.json`保留首次探针：managed子图未在delegated_task绑定中运行而被拒绝；Coordinator在绑定schema后触发探针的recursion_limit=5。这是夹具的到达限制，不能判为产品缺陷。建议Main只改诊断：临时seed快照、正常委派context绑定child，layout给对应grant，在ScriptedChat原bind方法记录后用专用sentinel停止；异常、原始清单与补丁恢复均保留。

分母分两面：最终model绑定的schema是Agent可见接口；compiled ToolNode是程序已注册路由面。optimizer初始注册14/15项、最终只提供6/7项，源码CandidateBoundary明确过滤，二者不能互换。相同profile/role/stage/schema去重；managed、knowledge、实验能力为此次六种有限配置，不能代表decision_only、host API或所有manifest的完整组合。隐藏注册路由的权限测试另列，不能通过不展示就当作已证明不可调用。

以下已阅读全文并核对生产判断，不是只检索测试名。收尾已核Main此次实际reports：三组6个主对照nodeid的setup/call/teardown在未观察、观察两次均通过。没有条件探针或独立值记录时，称“源码与oracle的独立对照审核”，不冒称已测全系统MC/DC。

|判断|有效基线与单条件反例|已核实的断言及剩余缺口|
|---|---|---|
|C03 `decision_data.py:213` owner/tool/call-id/status不匹配|`test_boundary_refactor.py::test_real_review_controls_survive_native_filesystem_eviction`有有效绑定且显式deliver_controls成功；同文件`test_final_delivery_rejects_changed_identity_or_original[owner]`及`[tool_call_id]`每次只改对应binding字段|两反例绑定结构仍合法；其它三个身份比较仍相等，目标比较改变则第一guard应拒绝。异常只匹配PUBLIC_DELIVERY前缀，owner还会被后续原件guard重复保护；不能据此声称每个guard都有强mutation oracle。tool与status独立负例尚未找到。|
|C08 `text_work_revision.py:30` type不符或count不符|`test_text_work_scoped_revision.py::test_revision_replay_after_adoption_preserves_receipt_and_cannot_create_new_node`的首次produce：ContentNode、1target、count1成功；`test_revision_boundary_rejects_wrong_shape_identity_or_authority[count]`仍ContentNode/count1，只把targets变2|反例明确断言异常、0模型调用、原payload不变。count条件的独立反例成立；单独object_type不符且count相等的测试缺失。其它misuse不能代替这个条件。|
|C18 `learning.py:196` 无release行或active版本不符|`test_learning.py::test_candidate_release_cross_project_isolation_and_revoke`在同一候选/客户可访问的scope下use(version1)成功，再release(None)，同一use(version1)要求NOT_ACTIVE|release(None)写入的是含NULL的行，fetchone结果为`(None,)`、真值为真；所以反例改变的是version条件，绝不是“无release行”条件。外国客户的拒绝发生在更早的_read，不能计到这个guard。未找到无release行时直接use的独立负例。|

三组都有明确局部缺口，尚不能把任何一组记为完整MC/DC。它们的程序结果断言也不证明模型对材料的语义理解或实际报告质量。此次最小交付是：完整基线的真实通过/失败/跳过/收集错误、六配置两类接口表面、24协议族对应的确切运行证据或未知、三组条件对照的范围与缺口；不要求先修绿全部旧测试。

## 收尾对账

1868已收集case：1726通过、112失败、21setup错误、9setup跳过；另2可选模块collection跳过。未观察/观察终态0差异。93个Python源文件：statement 11066/12710=87.0653%，branch 4050/5048=80.2298%。24协议族当前映射的候选实例均通过，不等于每族所有状态已覆盖；173个role/name union、45个中间件尝试也不构成接口覆盖率。

精确运行证据及哈希已存JSON；完整结果、代表失败归因、P1/P2建议与受阻动作见`neo-final-review.md`。本轮基线审核完成，未修应用、未调整旧测试以获得绿灯，未将程序覆盖率当成报告验收。
