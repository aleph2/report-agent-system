# Neo 本轮职责验证计划

状态：用户已授权执行职责覆盖验证；Codex 实施测试/执行，Neo 负责范围、oracle、问题判断和源码/trace复核。本文件不恢复暂停的 C1/batch1 产品重构，不改应用。当前任务是找出/解释缺陷，而不是维持绿色。

## 目标、既有证据与边界

以当前 5 类角色、44 项职责为分母，复用上一轮 149 个程序回归、四次合成实模以及真实对象/文件检查。每项分别记录 F（程序）、R（模型行为）、A（保存对象/文件），不把三者混成一个“通过”。C1-C3 新方案已确认但未实现；测试当前真实接口，不能手工注入新方案后当作已实现，也不以缺新字段冒称新 bug。

本轮允许：新增/维护参数化测试与现有 runner、临时合成 workspace/学习库、真实 native 图/ToolNode/适配器、MockTransport、合成文件检查，以及下述封顶真实探针。不涉及真实项目报告生成、C25、OCR、旧数据迁移/删除、发布、邮件、索引/学习新功能或改变原未知记录。

发现红例先区分 fixture/oracle、程序、模型选择、能力/环境。保留原失败、原代码/输入/输出，先查 root cause、定 P0-P3 和受阻动作；不自动停止无关测试，也不修改期望迁就实现。应用修复须另说明具体边界，经 Neo 判定后开展，不能作为“测试修绿”顺带实施。

## 首批可立即实施：三个共享测试组

只增加最多三个职责测试文件，复用现有 pytest、Driver、fake one-shot Model、临时 Workspace/Store 和 runner。fixture 是固定的合成委托、规则原文、冲突/缺料、明确格式参数和反馈，不从当前投影/导出的结果反算 oracle。测试脚本规定 fake 驱动的调用用于隔离程序；不把该顺序写进生产 Agent 流程。

### A：跨角色的要求、资料与部分结果交接

拟新增 tests/test_agent_duty_handoffs.py。

主要职责：C1-C6/C8、W01-W03/W05-W08/W12、R1-R4/R8/R9、L1/L7；不以一个成功场景标整组职责完成。

真实入口：deep_runtime.run_report → native task → content_tasks.delegated_task/bound_actor → 当前业务工具；显式选择材料经 text_work.produce/prepare_material 或 bounded_review 的实际独立工具 packet；返回经过中间件与最终模型 wire。恢复使用真实 checkpoint/正常入口，不手造平行状态。

最小 oracle/反例：

- A1：父任务明确给定当前动作、完整目标、要求与 Ref；验证实际子角色首输入的真实字段/文本。子角色没有自动继承全部父对话是既有平台事实，不把它当丢消息 bug。
- A2：Writer **显式**把当前 Criterion/Requirement/input_refs、选中 source/observation_refs 提供给 producer；核原文、exact version、限制、选择范围到真实 packet 的对齐。不要求自动携带未选择的所有资料或待实现的 C1 输出。
- A3：Reviewer 的已保存 scope/check/Criterion/required material extent 到独立 checker 的实际输入，未声明/错版本/不完整材料必须明确拒绝或如实保留未决，不能调用后保存“已完成”。复用活跃 bounded 路径，不恢复 submit_review 的 Agent 自写权限。
- A4：分别让 Writer/Reviewer/Layout fake child 明确返回产物 refs、缺料/未完范围及公开结论，核父下一模型输入原样承接；不要求程序替 child 补没有返回的内容。读独立 task_status/reconcile，区分 completed-check-but-not-satisfied、partial、unknown。
- A5：初次、正确 owner 恢复、错误 owner/旧版本、旧 receipt 的选择集；正确旧证据可复用，新材料/范围改变不能套旧完成，也不能重复旧未知。复用当前既有身份和业务版本机制。
- A6：错误 envelope/缺材料/超过当前内部材料 cap 在父子/独立工具两端均保留原因、未发送事实和范围；不得静默裁材料或把内部 cap 解释成用户取消覆盖。已确认数据 offload/deferred 可用，但控制信息完整、路径可精确恢复；不强制全部原文 inline。
- A7：合法选择与越权选择成对；程序正常权限/版本/预算拒绝不是“干扰”。比较最终适配器序列化消息，不只读原始归档。

复用：test_agent_result_delivery.run_role/wire_text、test_deep_runtime.Driver/ScriptedChat、test_task_supervision 的现行 ws/offline、test_producer_observations、test_review_input_correctness、test_required_source_spans、test_not_dispatched_recovery。旧 legacy fixture 不能直接替代当前配置。

### B：学习反馈→分析→候选/处置→宿主的真实链

拟新增 tests/test_agent_duty_learning.py。

主要职责：E1-E6/E8、W11；E7 先测宿主授权/可用性边界，不运行真实优化。

真实入口：learning_runtime.build_optimizer 或 run_optimizer 当前路径 → optimizer_tools → learning_text_work.learning_analysis_tool/adopt_project_fact → 临时 LearningLibrary 的候选/反馈处置 → 实际终态与宿主读取。worker/claim 分支只在它实际启用的配置中验证，不强制所有手动学习任务必须 claim。

- B1：两个同文不同 ID、不同 customer/job 的反馈；完整适用范围、前后文/证据和尾部限制到实际分析输入/下一决策可见。错域/错 job/陈旧 analysis 不能使用，不能因为内容相同合并不同处置义务。
- B2：project_fact 候选必须精确采用已授权实际分析结果，换值/借别的 job/analysis 拒绝；general_skill/customer_preference 是 Agent 策略，不强迫再文字工具重写。事实、策略、用户授权彼此不能代换。
- B3：部分反馈已处置、其他待查/失败时，不得只凭 saved candidate/流畅 final 把整个 job 标完成；处置 refs 与被分派反馈逐项对应，重复执行不得产生无依据的重复效果。
- B4：候选保存不等于 release、不等于报告已采用/有效。限定当前客户/项目，未发布不进入运行经验；只测现有 release/使用接口和宿主权限，不让 optimizer 新增发布权限。
- B5：独立分析 malformed/received-invalid/无响应/预算拒绝在学习端的持久化、重放与公开错误；不能用相同异常词就当未发送。复用真实 hook/MockTransport 验证，若兄弟缺陷出现，先保留红例而不直接复制另一模块修法。
- B6：Optimizer 最终输出与实际 candidate、disposition、仍未处置反馈对齐；经验被提供/使用/效果证据分开。假的“Done”不能改变真实保存状态。

复用：test_learning_text_work.py、test_learning_feedback_delivery.py、test_learning_worker.py、test_agent_result_delivery.py 的 optimizer 输入观察；test_learning_gepa_optional.py 仅复用授权/评估边界，依赖不可用明确 blocked/skip，不能当通过。

### C：明确内容/参数到真实产物，而非旧稿等价

拟新增 tests/test_agent_duty_artifacts.py。

主要职责：C7、W04/W09/W10、R5-R7、L2-L6；Agent 是否会选对参数仍留 R。

真实入口：当前 writer/layout 的注册 export 工具、export_snapshot、content_layout 的同一渲染实现、export_workbook、选择交付/读取/核对接口；实际 python-docx/OOXML、openpyxl cells/media 检查。不调用报告模型，不用 mock exporter 代替真实输出。

- C1：外部 fixture 给定 margins=25/25/25/15mm、gutter=0、1.5 行距、明确字体/字号/TOC 深度和给定表格内容；传入当前实际支持的参数，核最终 section/style/pPr/table/TOC、原段落/表格/media。Word 单位允许明确的机械量化误差，不用当前默认值当期望。
- C2：Markdown 表格/列表/软换行/图像/显式 heading 和节点级排版组合，完整原文/qualifiers 不丢、不重复目录；表头/行列/值保持固定 oracle。不对实现未支持的复杂表样静默简化；先作为能力差距明确记录。
- C3：Word/XLSX 真实保存、同 snapshot 配对、文件 link/byte digest；错误版本/未授权 Layout grant/旧 render/读取失败拒绝，不能把 failed read 当空文件或视觉通过。
- C4：给定相同内容仅改排版，content_versions/正文保持；给定新内容不得沿用旧审核覆盖。交付 selection 是版本选择，不等于整个报告接受。
- C5：渲染/视觉的文件、页码、crop 和 observation 绑定先 fake/真实文件机械核验；本机渲染或模型能力不支持时标 blocked，不能用 mocked 页面宣称真实版式可用，也不自动扩为 Excel 全视觉审核。

复用：test_content_layout.py（含真实 native Layout 返回）、test_layout_standard_controls.py、test_layout_table_controls.py、test_markdown_layout.py、test_content_workbook.py、test_artifact_review.py、test_boundary_refactor.py。实际产物缺陷要与模型没选参数区分。

## 其余覆盖分组与 44 项进度

coverage.json 逐项保留 F/R/A 所需与当前部分证据，初始状态不能全打 pass。其余组：

- S：公开接口/role 权限、最终 schema、状态/条件共性。复用上轮 149、round0 实际注册表及当前配置再核分母；改了装配/角色才重测相关组合。行/分支不代替独立条件。
- D：Writer 结构/算术依据/真实 source version、明确标准的首次生成。A/C 测程序，R 测选择；已存在原文截取/风险计算观察不是冻结实现或完整验收。
- V：Reviewer 独立材料/文件/视觉、完成/不满足/部分/缺料；机械绑定、实质工具和实际产物三段单列。不能用 top-K 资料代替完整必查覆盖。
- E：学习自动 job、候选/发布/使用/effect 与 optional GEPA。先 B/S fake；当前不新建学习系统，不把无依赖等同没有此职责。
- T：一个合成完整报告骨架贯通当前 Co/Writer/Reviewer/Layout 与 Word/XLSX，允许不同合法动作，核最终对象和未决事项。该低成本 fake 组合测试不是原业务报告真实验收。

44 是职责清单分母；实际接口/角色分母、有限关键协议路径以及条件/MC/DC 证据另列。不能以文件存在、某角色跑过一次或结果数量标整项职责通过。未实现、环境 blocked、模型未测和测试失败分别保留。

## 真实合成探针：本轮封顶及次序

本轮新授权覆盖必要职责验证，无需对同一范围反复向用户请示。Neo 审实际 runner/输入/配置/预算后由 Main 分波执行；这不是恢复旧 report run。

- **总上限：12 HTTP attempts，最多三波，每波最多4，包含所有 SDK 重试。** 不是 12 次成功逻辑响应；失败/重试会占本波额度，不能自动补齐。每波使用既有 RequestBudget(4)，最多三次新目录运行，总上限可直接审计；不新增预算框架。
- 现有 ledger 为 .runs/full-chain-budget-20261014/token-budget.db，170m 总授权、原 26m 未知保留与旧行不重置。两已登记模型单请求上界当前为2m；12次全未决的最保守新增占额为24m，不是预计实际费用。执行前重新读实际余额/bounds，未验证新模型直接0发送 blocked。
- 波1：Coordinator 一个明确目标/部分结果情景；Layout 一个明确格式标准情景；Optimizer 一个限定 feedback/job 情景；独立 content checker 一个完整材料任务。各1 HTTP机会，真实角色捕获完整 native messages/全 tools，独立工具用实际 packet/parser。
- 波2：Writer 表格生成、qualifiers 局部修订、artifact checker、学习分析各1机会。复用波1/既有四次的成功证据；不同工具输出契约不能仅凭同模型已测而跳过。
- 波3：仅按波1/2和 fake 结果补最高价值的未测反例/视觉能力，最多4。角色/资料/预期及能力在执行前具体登记，不为凑满额度随意增加。已明确失败的程序分支不拿新付费调用掩盖；不自动重放未知或为了得到成功换 ID/改 scope。
- 保持当前实际 mixed services/strict/SDK 参数，输出上限可沿既有合成 probe 明示8192，完整输入不人工缩 schema。官方 strict 本地编译不兼容可记录0HTTP，不能悄悄删工具/降 strict。兼容 endpoint 的通过不关闭官方 strict 问题。
- 小样本合成文件/材料，无真实报告/个人资料；新临时 workspace/library；真实动作只检查，不执行模型产生的工具调用（需要多步行为时先单列 bounded fake 环境执行方案）。独立工具可保存临时候选，但不采用进旧报告。
- AIMessage 无 tool_calls 不一律判结构非法：合法等待/询问/终局可能纯文本；接口解析合法与是否满足该情景行动义务分开。不得仅凭 JSON 合法宣称选材或判断正确。
- 没有真实返回/usage的未知继续保守占额。原账本 before/after 全行保护、原始输入/raw output/已解析结果/实际 wire/代码与prompt与helper hash 保留。只复核公开输出、调用和证据，不拿模型私有推理当根因。

### 最新限定：本轮验证1000万 token（用户直接授权）

用户新增：“验证、测试给你1000万token预算”。按当前职责验证阶段总上限10m执行，已发生本轮第一波86,705计入；不把此话自动解释为全项目170m再加10m，不重置旧实记/26m未知。phase起点使用 roles-live-wave1/ledger-before.json 的1032原行；此前四次46,603是上一轮证据复用，不再调用。剩余9,913,295不是必须消耗的额度。

本轮仍最多12 HTTP，但还必须满足更紧的10m保守占额；原计划“12次全unknown可用24m”仅是新增该限定前的估算，现不再作为执行准入依据。只改测试runner的宿主预检，不新建双账本或产品budget层：

- 持同一 phase 文件锁，覆盖预注册、整波至终验；固定原1032行及authorization/bounds必须保持。
- 逐所有新增行求本轮已用 + reserved/unknown上界；不采用可能掩盖旧行变化的总量净差，也不减去/释放旧26m。
- 本轮已占额 + 本波HTTP上限 × 已核模型最大单请求bound ≤10m才能启动整波。每模型目前2m，四HTTP最坏8m；重试同样占RequestBudget(4)。新模型bound未验证或出现bound_violation明确拒绝。
- 实际每POST继续使用原170m TokenBudget和共享HTTP RequestBudget；若一波最坏占额不容纳，少发/不发，不能只因预计prompt很短忽略unknown保留。当前0.086705m+8m允许一波；下一波重新核，不补齐失败。
- offline验证恰等号可入、超1拒绝、unknown占额、旧行漂移拒绝；预算预检验证不计实模行为通过。

## 完成标准与问题处置

每个新增 case 执行前固定职责、正常/拒绝/失败/恢复条件、独立 oracle、实际消费方；失败先确认送达/参数/原结果/包装/保存/后继输入哪层变化。共享 root cause 才归并，不把相似症状一概同因。

当前登记 44 行必须每行具备当前入口、F/R/A实得证据与尚缺项；接口合法/非法组合、关键协议路径、独立条件的目标仍100%，普通受影响代码分支95%目标未获测量前不报达标。全路径无穷，不宣称任意执行组合已穷尽。

测试保留历史失败和后来修正。确认修复与发现新缺陷分开，选2–3个关键不变量作零外部调用的隔离反事实/历史错误回放，检查原 oracle 是否真能抓住丢材料、错状态、旧范围复用。反事实不改工作树产品、不扩大当前调用权限；fixture/import 报错不能算杀死目标错误。

Neo 依据实际影响判 P0-P3 和阻挡动作；失败可隔离且不影响其他职责时继续其余测试。小样本真实模型不能证明长期稳定/全部语义，更不能取代最终第一合同全范围 Word+issues XLSX 和真实内容/视觉验收。新功能与修复另定边界，避免为了测试再造框架、固定Agent流程或永远保留并行真相。

## 发现能力校准：本轮新增判据

用户纠正：“为了暴露问题，主要不在于是否严格，而是测试用例的设计。” 本轮据此先写每个发现性场景的潜在错误、最小差异、现有测试为何未覆盖，再执行；不以更多幸福路径或更苛刻的断言代替发现能力。修复确认、发现性探索、测试敏感性是三种不同证据。

用户补充：“对，测试用例的设计也可以从trace中得到启发”。从公开 trace 提取角色、当前状态、输入、步骤及真实消费方，以合成数据替换业务内容；保留触发错误所必需的版本、范围、限制和前后顺序。不能把历史偶然动作顺序规定为唯一正确策略，不能从最终症状倒推未经证实的程序根因。

当前新增 18 个参数案例为有限程序切面的结果，不是 44 项职责全通过。尤其原生父子完整交接、显式 Criterion/SourceArtifact 到独立工具的全 payload、四种 DOCX 参数组合、学习的三类候选和两种失败重放、两条反馈只处置一条后的宿主终态，已有各自可判断的有限 oracle；不应永久笼统称这些切面“未验证”，也不扩大为模型策略或整项职责完成。

下一组优先三个场景，均不修改应用：

1. **任务恢复的当前性（新增跨步骤探索）**：原生首次 Layout 任务要求右边距 15mm，正常结束；同一 task/owner、同一 snapshot grant 的下一 delegate operation 明确本次修订替换为 20mm。比较首次与恢复后的真实子 Agent 输入及最终序列化 wire。新委托必须完整送达；旧任务、receipt、owner/grant 保留。原始 goal 存在本身合法；调查它是否仍被程序作为“Exact current application state”中的当前指令，与本次明确替换要求冲突。不能仅因旧 goal 保留就判 bug，也不要求尚未批准的 C1/current_goal 字段。若当前性标注确有冲突，先保存诊断、确认现有恢复合约，再判影响；不声称模型一定执行错。先 Layout 两种 managed 配置，再按共用机制决定是否补 Writer。
2. **历史信息失真反事实（敏感性）**：在测试内存层恢复 source 文本固定 240 裁剪、producer evidence_limits 删除两个已知错误，保持真实 native 消息路径、外部 fixture 和完整交接 oracle 不变。分别应因实际下一输入缺失目标内容而红，不能以 fixture/import/权限错误算杀死；产品工作树保持不变。程序受控大结果 offload 与有完整控制元信息的精确恢复仍合法，不将全部非 inline 表现判错。
3. **旧完成适用范围反事实（敏感性）**：复用 `test_saved_completion_reuse_requires_same_content_body_extent`，在测试进程内只忽略 content_check_scopes 的兼容差异，核 local/subtree 变化是否错误复用旧完成。其他材料防线不关闭；如仍由独立检查拦住，记录为冗余防御，不能武断说 oracle 无效。只有确认错误复用实际到达被测结果，原 oracle 却仍绿，才是该 oracle 缺口。合法旧 receipt 的历史回放不等于当前任务获验收。

真实第一波改为可区分的下一步情景，而非统一初始动作：Coordinator 已收到 Reviewer 明确 partial；Optimizer 已读取 before/evidence；Layout 已读取 capability/snapshot；checker 面对规则 75–100 与采用值 70 的明确冲突。单步模型未执行所选后继工具，故分别报告合法结构、行动适用性/公开判断，不能报告职责闭环；多种合理动作均允许。仍保持本轮总 12 HTTP、每波 4 的上限，失败不自动补齐。

## 历史 trace 吸收：12 个高价值机制，不是12套新增脚本

用户进一步要求：“trace里面应该出现了不少case，需要吸收哈”。以下从 `complete-bug-inventory-20261015.json` 的原 evidence 索引与本轮已核 trace 抽样；旧清单的状态不当作当前状态，发现输入相关性不等于证明历史因果。每行可复用当前参数化骨架；先检查已有测试是否实际覆盖必要对照，再补最小差异。不是恢复历史 Agent 入口或启用新功能。

| 场景/优先级 | 历史来源与最小差异 | 独立判据、现有证据及当前缺口 |
|---|---|---|
| TC01 先做：准则真实注册/保存（C2） | I01/I02，criterion-root-cause-review.json：说明可见但最终inner schema曾变dict。正常Requirement Ref，对照同项目SourceArtifact Ref或缺必填Criterion字段。 | 检查真实Co ToolNode最终schema、合法准则完整原文保存、非法类型/缺字段精确拒绝且无部分准则写入；不是再看原Python模型。可复用test_hierarchical_content的schema/commit骨架，但需当前配置实际入口；C1新字段不作为前提。 |
| TC02 先做：Writer结构决定与正文边界（W04） | I03、NEO-INV-001：结构决定可直接做，但不能借标题/辅助字段绕开实质生成。保持同任务，结构标题→实质段落/表格或缺关键body。 | 复用test_text_work::test_structure_decisions_do_not_require_text_model_but_are_not_body_bypass及payload绑定；正常结构不强制多一次模型，非法实质/坏shape不保存、不默默补成合法。schema可判与内容好坏分开。现共享CS关系闭包证据不能独证Writer主体。 |
| TC03 先核当前契约：Evidence来源/receipt合法池（W07） | I09/I10、NEO-INV-108，continuation16-evidence-batch-contract-review.json；把observation ID换成真实tool receipt，或只有原文观察却没有合法输出引用池。 | 用实际selection/输入装配确定合法池；不能手拼不存在的权限状态。如果当前输出必须有合法refs而池确空，明确不可执行，不用付费赌引用；有效对照应成功。计算用test_calculations和test_text_work::test_deterministic_calculation_adoption_matches_owned_result_and_needs_no_llm，证明算术/原receipt一致，不把算术正确升级为工程前提受支持。设计红例前先核本路径合法构造。 |
| TC04 直接复用：限定词改动与表格主体（W08） | C18 qualifier-only全body再生成的三表退化。只改qualifiers，table body/owner/version不变；对照body注入、错target/旧version。 | test_text_work_scoped_revision的native produce→adopt→revise→adopt及9种反例，最终Word/table可复用现有fixture；本轮合成实模另核R。不能为测试重新放开body修改，不能把已有schema拒绝说成已生成错误表。 |
| TC05 随后：实际页面与旧render组合（R6/L5/L6） | I08/L11及artifact版本误用：物理页≠printed label；同snapshot先export/render v1再明确调整生成v2，仍持旧page/crop观察。 | 先复用test_vision真实图像payload/页码/crop/cache和test_artifact_review的逐页extent，再补当前Reviewer/Layout注册入口实际接收图像、可追raw图像digest/页/版本。用小合成PDF/DOCX、真实读/渲染、Fake vision适配器，不用手写cs.observe当已读取图片。旧v1观察不能完成v2要求，明确当前v2观察可用。没有环境时标blocked；不凭mock页面推断视觉效果。 |
| TC06 复用并查兄弟：范围/游标/完整性（W02/R2/R3） | D08/I08/NEO-INV-017：原文总长曾被当已见长度，block ordinal/物理page/字符cursor混用。只改选择的unit/extent，原文不变。 | 复用source_tables的missing physical locator、cross-page pagination、required_source_spans的wrong ordinal/view/missing_block，及agent_result_delivery实际精确恢复。应保留selected/returned/total/next_offset语义，不把有ref或读一页称全文。其基本传递已有证据，不重复全跑；未覆盖的actual tool→下一输入才补。 |
| TC07 复用：缺料/64k拒绝后范围不能自动消失（C5/C6） | D03/I07、旧unsupported表样限制被省略；同资料改变“全部所选”和“超cap”。 | existing-first中的whole_packet_bound_before_provider_without_trimming、missing_actual_tail_is_precall_gap与本轮qualifier敏感性已有效。核错误含actual size/dependencies/producer_invoked=false，原task scope仍在，不把内部cap当用户取消要求。Agent应如何重新组织是R，不用fake固定唯一拆分方案。 |
| TC08 已证敏感性：旧完成的适用范围（R8） | H01：local_body→subtree_bodies，仅extent不同。 | 已保留actual保存/reconcile原测试；内存只删范围比较，错误完成确实发生并被原177行杀死。不是当前新增bug；保持反例和原生有效复用对照，不为增加测试数再造实现。 |
| TC09 复用/补最小新入口：unknown改ID或移材料（W05/R4/R7/E3） | R05/R06/R07、NEO-INV-070：同一未知目标改operation wording、input_refs/observation_refs形式曾再次派发。 | 复用149中的unknown/identity/生命周期和现学习失败重放；同exact关联只改ID/描述不能再调用。真正不同已授权材料/工作要有合法对照，不把整个source全部永久冻结。实际SDK/hook用于零派发与已发送区分；parser-invalid/received-length也不能写成unknown或success。不能仅测fake异常名称。 |
| TC10 复用产物：typed/Markdown/figure同一意图（W10/L3/L4） | L05/L11/NEO-INV-047：Markdown表绕控制、figure page字符串、选段处理吞图/列表。 | 复用boundary_refactor、layout_table_controls、实际DOCX/目录/媒体和figure物理页反例。同参数对typed与Markdown真实表都生效；paragraph selector不能丢内容；坏figure page不保存成可导出结果。复杂表样未支持就明确，不能把普通2列表通过当指南完整表样通过。 |
| TC11 已发现/其他部分复用：摘要与恢复当前性（C4/W01/L1） | D09旧假设固化；本轮同owner更新目标被原goal当前标签冲突。 | D-RESUME-01已确证managed路径P2但未修。复用summary_recovery/summary_context_provenance，旧summary/source不能覆盖当前角色权限、资源和明确新委托；不得把保留历史goal本身判错误。当前诊断不是可自动声称已绿的语义回归，修复合约另明确。 |
| TC12 小样本R而非伪程序保证：未知前提/少量资料升级成已核结论（W07/R4/C8） | NEO-INV-081/095/096/098：工具实际只得旧节点/缺原表或前提未知，却在objective/结论中声称已核/精确分数。 | 固定合成证据：规则要求条件Q，但Q未知；或原表有说明列却只供应部分。F核真实工具实际材料与限制完整保留、未凭receipt冒称语义正确；R检查产物是否明确受条件限制、未造分/未把“未定位”升级“来源不存在”。允许合理的未决、条件结论/继续调查，不规定唯一词句。需要独立模型/实际产物证据，fake正确脚本不能代证；不自动加新分数硬门。 |

本轮剩余代表路径中，C2/W04/W07/W08优先用TC01–04复用或补最小正常native案例；R6/L5/L6集中TC05共享小文件，不各建一套视觉测试。E7仍是optional dspy环境缺口：宿主授权、依赖不可用的明确拒绝可测，但不能为“44齐”装依赖或假称GEPA本体已验证。上述12项的合理性/测试来源不等于12项当前缺陷；先看证据再判是否须改代码。

## 2026-10-19持续验证：D-RESUME-01最小修复边界

用户明确继续修复并补齐职责验证；不是前批结束自动停工，也不是恢复暂停的C1/batch1。Neo只读设计/Main实施。先说明边界后实施，产品修复另留源码与fake/实际wire证据，不先跑真实模型。

**目标**：原始DelegatedTask@1仍是所有权/权限/审核契约；当前这次原生委派description是当前工作指令。两者必须明确区分，摘要压缩后仍保留当前指令，不能以旧goal的“当前权威”标签覆盖。

只改四处共享边界（新helper/字段均为拟实施）：

| 模块/入口 | 修改及保留 |
|---|---|
| content_tasks.py::delegated_task、现有_binding、拟只读invocation helper/临时绑定context manager | 在既有workspace+actor任务绑定中附本次delegate_operation_id和description；来源是已校验native call。直接工具上下文保留首次绑定，真实handler调用前可按当前next_call临时替换。返回副本、不跨任务泄漏。原register、owner、DelegatedTask版本、layout grant、review normalize/范围和operation digest/receipt行为不改。 |
| task_context.py::exact_task_context | assignment原payload/goal原样，明确goal是原始委派；增加server-bound current_invocation投影。替换笼统旧goal覆盖当前对话的note；本次工作仍受真实用户/系统权限与保存审核契约约束，不由description扩权。 |
| decision_state.py::compact_context | current_invocation.description完整保留，不进入bounded_metadata/preview；read_decision_state可读确切本次调用，summary复用同一投影，不新增summary状态。 |
| deep_runtime.py::BusinessBoundary.awrap_tool_call内部invoke_native | 每次实际handler(next_request)前，把next_call本次description绑定到同一当前invocation；覆盖原生completion followup的不同description，异常/取消可靠reset。仍原handler/request.override，没有第二Agent loop。 |

可附带Reviewer read_task_assignment docstring只澄清原始契约与当前调用区别（hierarchical_tools.py，若Main拟改须单列）；task_supervision.assignment可加同义docstring，但其normalize/reconcile/followup策略不是必改行为。不要因便于记录改assignment payload或历史digest。ContentStore.operation实际只存request_digest和response，不存完整request；不能声称从该表取到当前指令。当前投影来自现有native调用/原生checkpoint重入，非新持久化真相。

Neo初提“仅改标签”已由summary反例否定其充分性：只解决文字冲突，不能防止新Human被压缩后只剩旧goal，故未实施。当前小范围运行时绑定弥补这个可恢复性，而非把C1新状态方案带进来。平台复用限既有DeepAgents任务handler、middleware request.override、原生checkpoint、Python ContextVar/token reset和现存compact_context；不引入新平台API、存储或回路。

### 先固定fake oracle，再改源码

- 已有writer/layout×managed诊断转为实际输入oracle：原assignment@1/owner/task/grant/旧receipt原样，current invocation的ID/完整description与本次native call一致；原goal可保留但只标原始。managed False不凭空新增System机制，核其原生消息/权限不回退。
- 长本次指令尾部明确15→20；真实compact与WorkingSummary输入、摘要后下一模型有效wire仍含原样尾部和全文；不能只断言删了某句note。fake summary故意保留旧15，当前server-bound20必须继续完整可读。
- 同ID相同输入合法原receipt行为保持；同ID换description仍OPERATION_CONFLICT，角色/复用layout grant/变更review范围拒绝，不能通过新description授权。不要改变unknown/rearm/旧完成复用。
- 相邻task/角色隔离；异常/取消ContextVar reset；原生checkpoint续接及自动review completion followup的本次description与正要执行的handler参数一致，不用首委派代替followup。旧pending若资料不充分，明确保留不确定，不伪造新description。
- 所有断言使用真实native图/临时SQLite/当前最终schema与adapter序列化，fake只替换模型响应。保留旧诊断/红例，修复前应在目标oracle失败；不因构造客户端就算调用。

### 下一组trace组合

历史多目录：小fixture含root和三个child report，走native Layout→refresh_toc→真实Office render；实际DOCX只一个TOC字段且全部原文本保持，页面结构/renderer身份可追。目录页数不能从旧报告假定，真实render成功与单目录OOXML是不同判据。复用现有boundary/visual骨架，不重写原报告、不调用LLM。

修复fake/wire审过后，下一实模波候选最多4HTTP：恢复后的Writer当前“先调查不生成”、Layout旧15→当前20；Co经历实际不适用路径错误后的多种合法后继；独立文字工具缺必要分档条件时不得升级确定数值。每例先固定潜在错误/最小差异/观察点，允许合理读取和明确未决，不限定唯一动作序列；动作只校验不自动执行。Neo另核具体packet/runner及准入后执行，不为凑4派发。

保持本阶段累计已实记148,507、8HTTP、0新unknown；10m是本轮总上限，最多12HTTP包含重试，剩余最多4不是默认花完。全球170m/旧26m holds及原行保持，使用现有phase lock/admission，不重置授权、不重放unknown。E7正向缺依赖可后置，43有限程序切面不是全覆盖或业务验收。

## 最新顺序覆盖：2026-10-19先审核用例设计，不修复、不运行第三波

用户要求先设计能够复现真实缺陷的测试，固定同一oracle后再修、再验修。此前D-RESUME四模块/current_invocation方案退回**候选实现**，不作为本轮测试必需接口；Main本轮交付设计文档，应用/测试暂不修改、不执行新模型。已有H-OUTPUT离线修复结论和历史证据保留。

### TD-R01：同责任方恢复后，摘要不能使本次委托失去权威可获得性

- 真实来源：D-RESUME-01公开native输入、task_context.py:53/93；已有test_agent_duty_handoffs.py:96诊断。原任务goal保留合法，缺陷是旧goal被当前权威标签覆盖本次合法修订。
- 最小fixture：Layout原15mm→同task/owner本次明确20mm并保持其他限制；Writer草稿→本次只调查不生成作兄弟。managed True为主失败候选，False仅按实际配置作控制。
- 操作：真实native resume，保留合法grant/审核契约；用现有WorkingSummary真实compaction（test_summary_context_provenance骨架），fake summary只保留旧15/旧草稿。摘要须确实移除原新Human的保留区，不能假称触发。
- 固定行为oracle：摘要后下一真实模型请求/adapter wire，在当前原生委派消息或明确当前的server状态中仍含本次完整指令（包括长尾替换和限制）；只在被标历史摘要/引用的文字中出现不算当前指令。旧goal可以作为原始历史留下，不能被声明为本次的覆盖依据。原assignment版本/owner/grant/旧receipt不变。
- 不要求字段名current_invocation、特定ContextVar或某种新实体。完整本次Human合法保留/恢复也是可接受实现。直接删note却仍让摘要后新指令消失，必须失败。原始不压缩送达是对照，不是复现成功。
- 先观察现状是否在该目标oracle红；summary未触发、权限/fixture失败、其他异常不算复现。尚未运行，无新增bug结论；现P2诊断本身保留。

### TD-J02：任务需要的公共判断，结构、传输、可消费分别验证

- 不新建全工具统一verdict schema；来自各自任务及当前实际契约。独立checker在bounded_review.py:23/44已有observation/limitations、execution_state、verdict、reason、coverage、check_results和findings。Writer是ContentNode body/claim_kind/qualifiers与可选generation_notes；Learner是findings及可选project_fact；通用analysis是公开文本，不因字符串就判bug。
- 复用合法当前checker fixture，设计completed/not_satisfied与blocked/null的最小差异，给reason、observations.limitations、coverage.unchecked、check_results.remaining、findings各放不同长尾限定，保持实际证据索引与任务绑定有效。真实native inline/offload→下一Reviewer序列化wire逐字段等于独立原结果/保存record；不能只比hash或看receipt存在。
- 已有test_agent_result_delivery.py:195–226覆盖reason/verdict/state/coverage/check_results及末尾警告，尚未逐字段独立核observations.limitations/findings；扩展范围据此定，不声称此前完全没测。
- 通用analyze_text/analyze_evidence沿test_agent_io_siblings.py:83–109，三角色保留明确“支持A、反驳B、Q未知、所选范围”的公开finding原文及定位，下一wire全等。当前evidence_analysis.py:246返回analysis字符串；该测试验证传输，不假造当前存在分字段判断校验。
- fake后继可以选择继续调查/记录未完成以证明信息可被消费；它不证明真实Agent会正确理解。真实模型语义验证另以原始条件、任务和原文校准，不读取私有推理、不把合法结构算内容正确。

### TD-G03：指南表样缺失，不能仅用schema合法代替任务完成

- 来源：layout-feedback-rca-20261016/guide-table-execution-root-cause-20261016.json、table-material-program-transformation-proof-20261016.json、writer-table-material-selection-cause-20261016.json；区分程序压缩的历史机制与当时实际选入文字工具的材料，不能倒推当前仍剪原料。
- 独立合成fixture：完整表有两级表头、分级行和会改变解释的脚注；对照只移除选中材料里的原表/脚注，其余委托不变。原始完整资料仍在项目内，不得把“此次未选入”说成“项目没有”。
- fake程序oracle：真实工具packet准确反映实际选中内容/范围，不自动补入未选资料、不静默裁掉所选；模型公开的技术限制（放现有qualifiers或analysis/observations）及所剩工作到下一Agent输入完整，不能被generation/process notes或completed状态掩盖。给定partial返回不等同整体成功。
- 内容oracle：后续真实合成探针才判断工具是否如实说明缺原表/条件，未发明遗漏行或确定评分、未宣称已按完整指南表样。允许限定范围的草稿、未决或继续取材；不硬规定单一路径。技术不确定性应保持报告可见，但不凭现有schema推断其必然出现。若fake脚本直接编写正确结论，不能用来宣称模型做对。
- 本轮只设计，不发起真实调用；如果要判断“本次结构必须含哪些内容”，先从该任务原文定oracle，不能顺手更改全部工具contract。

### TD-T04：历史多目录的当前真实组合

- 已有test_boundary_refactor.py:102是一child report、真实DOCX单TOC；content_export.py:233已限定report且depth0。不能称该已知局部修复没测，也不能当三child+refresh/render组合已过。
- 新fixture仅root+三个child report；原生Layout明确toc=True→实际导出→refresh_toc→真实Office render。DOCX刷新前后一个TOC字段、一个目录标题/逻辑目录且所有独立正文文本保持；render绑定刷新后的准确export/digest，真实成功，不能mock页面当真图。目录可以合法跨页，不将“目录只有一页”当判据。
- fake只替换模型动作，真实docx/refresh/renderer；不重生成原报告，不加LLM。当前尚未运行。

上述设计先供审核并冻结oracle，再由Main实施测试。目标是复现/区分当前机制，不为红而发明未实现要求；同一用例应在修复前命中目标失败，修复后通过且正常对照不回退。
