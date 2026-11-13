# 当前计划清单

Current Stage 1 work follows the [2026-11-10 9a split](../docs/reviews/stage1-9a-entry.md) and the dated checklist below. Earlier task lists are retained as history, not authorization to resume G4/G5.


## Active G4 repair — 2026-11-03 (ordered review gates)

- [x] H1: source anchors, versioned dispositions, shared completeness guards; actual input extraction and omission matrix; review tag `m1-fixes-20261103-g4-h1` (457 passing affected tests; independent reviews accepted).
- [x] Owner H1 review before H2 (approved 2026-11-03; entry-derived capabilities and readable brief added to H2).
- [x] H2: ID attachments, fixed-source extraction, structured small planning tools and persistent rejection cap; 620 passing affected tests; review tag `m1-fixes-20261103-g4-h2` ([verification](../docs/m1-g4-h2-verification.md)).
- [x] Owner H2 review before H3 (approved; current scope frozen for H3/restart).
- [x] H3: candidate/source-access brief, preserved real-attempt replay with disclosed reference adaptation, scripted full path and fresh full suite (4,865 passed / 0 failed / 9 skipped; two optional collection skips); review tag `m1-fixes-20261103-g4-h3` ([verification](../docs/m1-g4-h3-verification.md)).
- [x] Owner H3 review (approved; Option A exclusion check requested before restart).
- [x] H3.1 shared exclusion evidence check, trusted owner reduction display and stopped-attempt replay; 584 affected tests passed, with separate native scripted controls and retained timing failures ([verification](../docs/m1-g4-h31-verification.md)).
- [ ] Owner H3.1 review before fresh staging, budget and applicable model checks.
- [ ] Owner restart approval, new staged candidate and checkpoint availability; nine-item report acceptance.

Details/limits: [G4 repair plan](../docs/m1-g4-repair-plan.md). No paid calls,
financial-request replay or old-run revival during offline work. The owner authorized
H2/H3 completion emails (sent) and one H3.1 completion email after publication;
polling stays stopped. Retain historical tasks below.

## 2026-10-29 用户确认的待办

- [ ] **P3 暂定：ONNX Runtime 原生导入段错误**。只记 backlog，当前不升级依赖或修改检索实现。2026-10-29 的 `clean-room-full-fresh-01` 全量回归 shard1，在 `tests/test_tool_discovery.py::test_local_embedding_missing_cache_never_downloads_when_local_only` 导入 fastembed → onnxruntime 时发生 `Fatal Python error: Segmentation fault`。原环境 NumPy 2.5.3 / ONNX Runtime 1.30.0 / fastembed 0.8.1；不能据栈推定版本不兼容、内存不足或并发导致。43个未完整节点串行续验全部通过，另3次同环境独立导入通过；源和运行时 pins 未变。Neo联合复核3920 passed、9 setup skipped、0 failed，另2个可选模块未收集；原崩溃证据保留，不能称问题已修复。影响为离线回归稳定性；本轮已以串行续验容纳，不阻断本组合成验证。后续若复现，先核原生core/依赖与进程状态，再做最小复现；不盲目重跑付费模型。负责人Main，Neo复核；无新证据前不扩大修复范围。证据：`/home/dysun/report-storage-isolated-20261028-runtime/clean-room-full-fresh-01/run-1.log`、`serial43-manifest.json`、`phase-serial43.json`、`onnx-import-probes.json`、`combined-review-record.json`。

## 2026-10-28 运行监控与数据库并发 backlog

用户最新执行顺序：保持旧真实运行停止并保留历史及未知预留；先完成统一存储入口、原件外置和会话重复内容修复，使用独立 fake 数据库和相应回归；从 OCR 前 fake 数据配合真实 LLM 完整验证并由 Neo 审核；之后实现 Tool Search 再从干净环境做一轮 OCR 前 fake + 真实 LLM 与 Neo 审核；最终从头使用真实数据生成报告。fake 预算每轮 5000 万、单次 600 秒；真实项目总授权 2 亿 token（保留既有用量与未决预留）、单次 1800 秒；所有模型调用 high。邮件停止。不在旧运行上热改或恢复。

- [ ] **统一存储访问后续切片**：本轮首片只统一原件与页面材料读取入口，并把新导入原件外置；其他业务 SQL、checkpoint 和 token 账本尚未统一，不能据此声称全系统 DAO 已完成。按用户“小步快跑”决定，基于完整端到端 fake 证据安排后续边界收口；SQLite 继续作为实际后端，暂不接入或迁 PostgreSQL。保留现事务、权限、预算预留与恢复语义，不将不同事务硬合并。

- [ ] **最近返回索引过大（用户要求本次尽量一并解决）**：检查 `TaskContext` 注入的 `received_returns` 及 `read_summary_observations` 返回，识别可无损合并的重复元数据与说明；保留来源、版本、完整性、权限边界和按需读取原文能力，让智能体自行选择需要的材料。以已保存真实请求和独立合成案例比较体积、可发现性与语义，验证摘要、恢复及跨任务隔离；不截断或丢弃必要证据、不添加固定流程。不改暂停中的运行，纳入工具发现优化评估；现阶段未经验证。

- [ ] **高优先级待验证：payload 复杂度与处理耗时**（用户反馈，2026-10-28）。核查模型/工具输入和结果 payload 的大小、嵌套、重复封装、序列化、哈希、来源绑定、上下文投影及持久化开销，区分本地准备、外部模型等待和结果处理；结合已保存Trace及隔离合成负载测各阶段时间与资源，找出可证实的瓶颈。保留原始资料、必要来源关系与可按需读取能力，不截断正文、不写死智能体流程。续跑日志曾长时间无新事件，但目前日志不覆盖本地工具阶段，尚不能断定由 payload 导致；补齐非阻塞阶段日志后再验证。 用户授权的进程状态采样显示一个线程等待 WSL/Windows 文件系统 I/O（p9_client_rpc），但未读取文件或数据库，不能据此断定具体文件或耗时根因。

用户最新授权：真实项目同一轮总预算调整为 **2亿 token**，包括此前启动、续跑、helpers及未决预留；2026-10-28在途宿主仍受原1亿上限保护，安全边界核账后再应用新授权，不热改在途进程或释放预留。历史1亿描述保留为当时授权。

- [ ] **高优先级 P1：系统级鲁棒断点续跑**（用户决定，2026-10-28）。系统中断后应恢复原项目、原任务和原checkpoint，在Co与Writer/Reviewer/Layout等子任务之间正确交接；已确认完成的步骤不重复，已发送但结果未知的外部请求保持防重放及预留，不能靠删除reservation或伪装新任务绕过。覆盖本地数据库/进程中断、模型或工具未决、子任务完成但父任务尚未接收、重复恢复、身份/版本不匹配等边界；补齐结构化恢复状态与日志，不把已保存视作成功。保留原测试，使用独立合成故障及正负控验证，Neo独立复核，再按用户授权恢复真实项目。当前04已因子任务中断无法透明续接，阻断本次交付；目前只在验证已证本地pre-model SQLite BUSY场景，不将其宣称为完整恢复能力。

- [ ] **P2：进度监控不得阻断报告运行**。真实04在 `ExecutionProgress.save` 提交时报 `SQLITE_BUSY`（15秒连接等待、journal_mode=delete），本次运行因此中断；见 `.analysis/real-ocr-native-20261028-04/neo-terminal-operational-error-public.json`。Neo 一次只读长事务与失败时间可能重叠，是需要核实的候选原因；目前不能断言唯一持锁者或根因。
- [ ] **仅日志的运行中监控**。评估现有进度和可公开Trace；针对缺失的启动/委派、Writer成果、Reviewer开始与完成、导出、模型及工具错误、用量、未决预留补充轻量结构化事件，记录时间、角色、阶段与必要的可核验标识，不记录材料正文、凭据或私有推理；禁止以事件状态替代内容或工程验收。监控读取日志，不在运行中打开业务SQLite。
- [ ] **查询与索引性能待证**。在独立合成库或终态副本，对原监控查询测量耗时、事务持锁时长和查询计划，分别验证索引、分页及减少扫描的效果；SQLite索引/查询设计可能导致读取慢，目前只是待验证假设。比较日志方案、短读事务与必要时WAL/迁库，结合文件系统与可靠性约束选择最简单有效方案，不因单次 BUSY 直接迁库。
- [ ] **验证并发与不丢事件**。保留原测试，构造大资料下监控与真实写入并发场景，验证观察端不阻塞提交、日志记录顺序和失败行为；核验离线内容复核仍可准确关联证据。保留04 checkpoint、历史账目和未决预留，不自动重放、释放或重置未知请求。


## 2026-10-28 OCR 前 fake 运行问题与后续计划

实际证据：`.analysis/fake-ocr-round-20261027/neo-terminal-review.md`，独立 high 对照见 `high1800-diagnostic/neo-result-review.md`。原运行未完成，Reviewer 未运行；两次 600 秒期限请求的远端结果未知，两笔预留保留。high 对照 68 秒返回且结构合法，但并非报告验收，也不能单独证明 max 是超时唯一原因。

- [ ] **本次修复：技术失败误报预算**。下一次运行宿主区分真实额度不足、未知结果、技术失败，复用已有精确错误码；保留原超时和未决请求的边界，不改历史 trace/账本。
- [ ] **本次修复：观察引用诊断**。区分引用不存在与存在但属于其他任务；保留严格权限及防重复保护，不自动把 operation ID 转成 observation ID。
- [ ] **本次配置：全局 high**。按用户最新决定，新运行的可配置模型推理强度统一 high；历史绑定不热改，新任务摘要使用 high，旧任务摘要配置不热改；保留各 provider 的实际视觉协议。对照原测试，确认哪些断言因需求变化需调整，保留其他行为。
- [ ] **待评估：文字工具输入包装**。对照本轮 trace 识别实际重复，保留原文、位置、来源版本、表格和不确定性，不按长度截断；证明无信息损失后才改。
- [ ] **待评估：源证据的状态强化及正文重复**。覆盖“未证实”与“已确认未执行”、资料未提供与不存在的区别；保留必要限定，不靠固定措辞或删除判断通过测试。
- [ ] **待研究：长调用诊断与流式能力**。原 max 请求服务端根因未证明；若考虑流式，先验证分片/终止、usage、未知预留和恢复，不直接启用或盲目重放。
- [ ] **Layout/Co 职责及报告呈现**。以实际需求和 trace 澄清何时由 Layout 设计版式；不强制固定阶段，也不把 Excel 视觉/打印可读性加回验收。

本次执行顺序：针对性测试与修复 → 全量回归并由 Neo 复核 → 新的干净 fake 原始扫描资料、智能体自主 OCR 和报告审核端到端验证 → 依据结果继续到真实项目。fake 每轮 5000 万 token、单请求 600 秒；真实每轮 1 亿 token、单请求 1800 秒，均包括 helpers 和新预留；不发送邮件。

## 最新状态索引（2026-10-26，优先于下文历史阶段描述）

full03已3378通过、0失败、9环境setup跳过（两可选collection模块未覆盖）。当前同案synthetic-native-20261026-01已完成原1+6项Reviewer保存，正在continuation01让真实Co收尾，Layout处理TOC。取消120计数；最新每轮50m standing授权，无独立累计审批；原在途host仍受原30m保护，远低该值，不热改。实时以.analysis/reviewer-complete-materials-20261026/current-work-state.json及continuation01/result.json为准。下文旧“未实施/不得full/旧T7/4m/120”按原时点保留，不覆盖最新用户决定。

## 2026-10-25 当前最简交接实施（已获授权，纳入Langfuse补审）

当前授权与范围见plan.md最新节；本轮证据`.analysis/minimal-handoff-implementation-20261025/`。以下未完成项已获实施授权，不再等待重复确认：每片先针对性RED再代码/相关GREEN，保原测试；Neo逐项核技能动作和产物，实际DeepSeek审有效提示。不full/report/平台实验/旧unknown重放。此前“待确认”描述保留为设计阶段历史。

当前详情见plan.md最新节与.analysis/minimal-handoff-contract-20261025/implementation-plan.md；以下逐片执行，状态依本轮实际证据更新。不覆盖历史结果/未完成项，不跑full/report，不重试旧未知。

- [x] 1. 既有save的V4可选成果声明：先RED，验证selection-only/双稿选择/排除依赖/原owner，保持旧save路径。
- [x] 2. 原native返回与读状态提供可恢复声明投影；同一句柄精确复用Snapshot，显式导出/Co选择/Layout权限贯通。
- [x] 3. 原始完整commission+标准基准与局部scope独立绑定；同事务保存task/source权限，完整旧scope复制仅新intent身份不同。
- [x] 4. submit/reconcile/显式reuse/最终delivery采用基准及全部读取方一致；不串用旧pass、不将局部审核当完整验收。
- [x] 5. 原native intent调用前reservation/真实checkpoint恢复边界；未知不重放，返回Command不丢，独立新intent仍允许。
- [x] 6. V4实际Co/Writer/Reviewer/工具提示及provenance一致；实际DeepSeek审核提示字节，Neo核相关新旧测试和源pins。
- [x] 开发退出记录：仅相关RED/GREEN、兼容/负向机制与Neo意见，不声称真实自主协作/新full绿/工程通过；full或报告须另定边界。

2026-10-25本轮闭合：V4六片实现、Langfuse补审映射、实际DeepSeek差异审查/Neo独立复核完成。350P为审查前冻结版，最后D1/同parent权限闭合后117P为最终受影响版，不能相加成467独立例或称最终源全量绿。347旧tests/42旧prompt/6运行文件均不变。权威记录为.analysis/minimal-handoff-implementation-20261025/main-final-record.json、verification.md及Neo受限接纳。未启动报告/真实自主评测、full、OCR或unknown重放；后文旧T7运行状态为历史，不是当前active。

唯一设计和验收细节见[plan.md](plan.md)。状态：本轮实现及一次全量发现问题已定向闭合；全量实际3176P4F9环境setup跳过，修后两批33P/107P，不能称最终源同版全量全绿。不覆盖旧运行，不恢复报告/邮件/监控。

- [x] 用Graphify建立生产源码关系图，并说明覆盖/推断限制。
- [x] 根据实际trace校准问题边界，形成带依赖、测试及风险的实施计划。
- [x] 实际DeepSeek评估两项最小候选，Neo核最终稿；形成high/信息保留修订和18组定向验收点（仅规格，未写/跑测试）。
- [x] 与用户讨论计划中的未决选择；Neo复核具体最小边界。
- [x] T0：冻结既有public trace哈希与两例自纠初错证据，新增合成离线RED；不重放旧远端请求。
- [x] T1：技术操作身份由现有原生运行时持有，保留幂等和未知保护。
- [x] T2：Relation端点条件进入实际模型契约，原验证保持。
- [x] 检查点A：相关RED→GREEN；原契约/权限/回执测试不降低。
- [x] T3：人读表达与技术溯源分清，真实限定和Evidence完整保留。
- [x] T4：削减重复并保精确恢复；full01暴露的旧v1读取开销回归已修，旧oracle不改，受影响家族通过。
- [x] 检查点B：实际SDK输入与prompt版本可追溯，必要提示词审核完成。
- [x] T5：慢请求/参数纠正/远端未决的状态与恢复边界验证。
- [x] T6：执行唯一全量并闭合发现的4项失败，披露9环境/2可选缺口；修后定向通过，未取得最终源同版全量绿，不拼接计数冒称。
- [ ] T7：另核安全范围/授权/同账本预算后，一次真实自主协作验收。
- [x] 最新授权：当前单次模型deadline/HTTP read改600秒，core96P/adapter25P；历史1800记录不改，不重放未知。
- [x] 澄清并在专用learning环境验证GEPA/DSPy兼容4P；不是缺包，也不是已证明优化收益，不重写原full结果。
- [x] Neo本轮已独立核技能实际落实与证据，并把持续监督决定追加现有用户决策记录；后续分工沿用，不新增运行阶段。

T1–T5实施/相关RED→GREEN已完成。Neo冻结前发现独立optimizer误读报告配置并修复；唯一full01又抓到3项旧history读取契约回归及1项新30ms测试的错误阶段假设，full保3176P4F9S事实。源修复/测试校准后，33P与107P分别通过，旧测试文件零修改；原case和同token账本字节一致。详见.analysis/implementation-skills-20261024/verification.md与post-full-repair-verification.json。T7真实自主协作、质量及延迟改善未验证，不自动派付费请求或重试旧未知。实际DeepSeek设计CLI已执行，不混称没有模型活动。

T7最新直接授权：准备03 revision2三源两行+原7义务，真实Co high自主交接，单call600，cap4m admittedused+held/120HTTP/7200s准入，singlebound2m/原账本不变；先实际DeepSeek+Neo确认再唯一派发。当前仅分析host与离线检查，run尚未启动。详见03实际prepared/approval/started/result，不以本清单代替实际状态。不再full、无邮件/自动监控/旧unknown重放。

当前T7在唯一新运行中：.analysis/synthetic-native-20261024-03/started.json实际2026-10-24T05:50:14Z，session70361/pid1104；首Co实际high/65536/read600已核，正在等待真实自主协作。不得再次prepare/run或盲重试。进展以该目录result优先progress/observe_readonly为准，不以旧02运行。

T7终态：唯一03已停/failed预算准入，39HTTP成功返回、1known_not_sent，2027610used/newheld0；Writer成功，Co仍在冻结前后准备，Reviewer/ReviewRecord/Office0。本项未通过，不能重跑。当前只读根因诊断和独立终审，结果03/result.json高于progress；旧rows/holds/授权/报告保持。

T7独立终审/根因分析已结束，见03/final-assessment.md与main-final-assessment.json。完整协作仍未通过（本次唯一尝试已完成），保持停止，不自动续跑或改源；原reviewer/Office验证仍缺。另已补审本地STATE_PATH_NOT_FOUND，不能说没有错误或纠正成功。

历史设计阶段：四项最小方案由实际DS75055+Neo终审设计接纳；随后用户明确授权实施（下节），此前“尚待确认/不改代码”不再是当前状态。入口.analysis/handoff-minimal-plan-20261024/final-plan.md及main-final-design-record.json。旧T7仍未通过，不因方案接纳打勾。

当前授权增量：先新增定向RED，再改最小源，Neo监督/复核，实际DeepSeek审核提示词。保留旧接口、旧测试、原03 case与账本；不加预算、不跑报告、不重试、不跑全量、不启邮件/监控。证据目录.analysis/handoff-implementation-20261024。

- [x] 冻结本增量前source/tests与保护case/ledger hashes，复用Graphify导航并读最新生产代码。
- [x] saved-reference新12例先RED后GREEN；None/[]仍旧严格freeze/原请求身份。
- [x] native-return/最终SDK/profile新5例先RED；正在实现V3显式接口及原生返回metadata。
- [x] Neo检查回执结果shape和重放校验边界；补充RED暴露后按最小范围修正，待合并GREEN。
- [x] 新实际提示词字节经DeepSeek条件评审；按其正式第5节必改与第6节四个精确句采纳，旧Co/Writer基础源不改。
- [x] 相关新旧批182P；Neo最后两项metadata/proof边界先RED2F后修，受影响原生/恢复31P。两批重叠不拼总数、不冒称全量。
- [x] 对本轮前487文件hash复核：343旧测试/39旧规则源不变，仅7已授权既有源变化；6保护case/ledger文件不变。13项最终源清单含3新rules/3新tests。
- [x] Neo最终neo-final-review.json accepted=true，SHA663611900ba29d52fdb6433ffeb341e29a6b0ce18a44f019710ca0c3acc9754c；仅本轮V3保兼容局部实现/定向机制验证，四项已报P2闭合，不是最简交接设计或真实协作通过。

本轮定向实施/相关验证及Neo最终复核已完成；细节见本轮verification.md与neo-final-review.json。未宣布真实自主协作改善；单纯保存成功/冻结不等于审核、验收或任务完成。不加预算/不重跑报告或全量，后续必要性分析不等于新改造许可。

最新需求澄清：用户重点是‘这么做的必要性’，而非仅拼接性能，并肯定Agent Skills需求分析，要求以后参考。Codex/Neo同意：验收物与标准的准确版本绑定必要；Co逐节点回读/手抄Relation/先显式freeze不是用户需求。V3只是保现API的局部减负，未达到最简业务交接；把绑定移入交接内部仅设计方向，尚未扩张实施。未来先分析目标、每步输出/消费者/必要性，不能把已有schema当需求。已存.memory/requirements-before-interface-20261024.md及Obsidian17；不再强行访谈/另造规格或批准环。

## 2026-10-26 当前设计：actual03 Trace整改（方案完成，未实施）

本节为最新状态；前面的T7/旧运行记录保留为历史，不是当前在途运行。

- [x] 全97模型尝试/实际工具/Office Trace审计，Neo复核。
- [x] 完成程序与Agent职责方案及S0-S5/V01-V11实施/验证计划，Neo精确稿复核；见.analysis/trace-remediation-plan-20261026/plan.md。
- [ ] 获得实施指令后，先补actual03跨段最终SDK失败回归与兼容负控。
- [ ] 按计划修typed投影/清理，复用声明导出帮助；Reviewer独立配置/保存返回贯通。
- [ ] 相关原/新定向回归通过、Neo审实现、具体提示词变动经DeepSeek审。
- [ ] 后续实施授权范围内，判断是否集中一次full更新，再另核fresh fake+real资料/预期/现账与运行边界。

当前不启动模型、报告、测试、恢复或加款；旧unknown/数据/源历史保持。

## Backlog：actual03 呈现改进（2026-10-26）

来源：用户明确要求将Excel Note、重复说明等呈现问题记入backlog。优先级P3；状态待处理，不阻断当前主链路修复。证据：.analysis/synthetic-native-20261025-03-trace-audit/report.md。不是本轮Writer英文提示词泄漏。

- [ ] **Excel固定英文Note标签**：定位content_workbook.py:102，改为适合成果的显示方式；保原备注全文、数值/限制/来源和字符串安全。用含note的fake workbook窄回归，检查实际单元格。
- [ ] **Word正文与qualifiers重复呈现**：减少重复显示，不能删必要限定、差异、未完成项和来源。以现有报告作对照，核实际正文及渲染页，不仅匹配字符串。
- [ ] **技术定位直接进入成稿**：对qh5/manifest text; chars等提供可理解的引用展示；原完整机器定位/证据链继续保存，不能虚构原PDF页码或移除可追溯性。验证展示和底层证据均正确。

这些事项尚未实施，也未纳入本轮主链路必修；后续按实际变更独立验证，不以减少token为由删业务信息。


## Backlog：按决策用途组织材料（2026-10-26，用户指定后置）

- [ ] 先定义每次模型决策的输出及消费者，再据此确定输入及工具返回；不以固定字符数代替信息需求。当前先实现完整、去重的Reviewer业务材料包；不在本增量增加动态材料选择/通用pin机制。


## Backlog：既有导出参数诊断（2026-10-26 DeepSeek/Neo审稿）

- [ ] P3：Word/XLSX导出在snapshot_ref与deliverable均未给时，目前以INVALID_CONTRACT拒绝；可改善为清晰业务诊断。已拒绝执行，非绕过互斥校验，不阻断本轮完整Reviewer材料呈递。保留现权限与所有权，不因Co先创建快照就授予Writer额外导出权。


## Backlog：本轮Trace新增与未闭合项（2026-10-26）

来源：用户要求记录技能补充及“实际效果不等成功回执”，并查看现有backlog。只登记/分类，不在当前运行中改源码或注入修复。严重度与是否阻断当前动作分别判断；当前最终交付/版本适用性核查仍是本轮验收义务，不能借记backlog跳过。

- [ ] **R26-01 提交诊断精确化（P2，已证）**：submit_review指出具体scope/check/参数路径/缺失bodyRef/可用receipt类别；COVERAGE_OBJECT_OUTSIDE_SNAPSHOT须区分真实越快照与coverage inventory不支持Evidence/Relation/SourceArtifact类型。保原owner/版本/extent/scope验证。证据：submission-attempts-final.json、submit-review-neo-diagnosis.md、live-diagnosis-supplement.json。
- [ ] **R26-02 有效收据与摘要事实保留（P2，已证）**：摘要后完整合法UUID未保入可见notes；错误“旧收据作废”假说被固化，与五组等效重复取证的公开理由一致，并增加重复取证风险；其单独因果贡献未量化。保同actor/task/version有效事实和精确恢复入口，区分事实/假说；不把业务46对象完整等同receipt已可用。证据：post-summary-public-working-notes-1388.json及Neo公开归因（951→957字段路径倒置；1219假说→1381固化）。
- [ ] **R26-03 可观察验收计划（P2，证据缺口）**：应呈现标准→验收物/版本→证据/方法→判定/未完的简短工作单元；现首个todo为事后活动清单。不能推断无私下规划，也不新增固定planner/强制逐条独立调用。证据：reviewer-plan-neo-review.md。
- [ ] **R26-04 失败与重复的进展反馈（P2，设计覆盖缺口）**：现守卫未覆盖失败submit/read_content_export/observe_evidence这类序列；按可验证未解决条件及新增证据评价进展，不按任意次数/同错误码硬停，不冒称本轮已触发降级。优先修诊断与事实保留，再评是否扩反馈。证据：progress-guard-neo-review.md。
- [ ] **R26-05 非法JSON与其他初错回归（P3/按根因分别核）**：保885/1520两次submit非法JSON、4schema/9handler拒绝/2成功的完整漏斗；另保Writer TEXT_WORK_OUTPUT_CHANGED、Reviewer CONTENT_SELECTION_OUTSIDE_SNAPSHOT及STATE_PATH_NOT_FOUND。先离线最小复现，区分Agent候选错误、程序守卫正确与说明不够；不自动改写判定JSON或以最终成功消除初错。
- [ ] **R26-06 文件工具与资产路径边界（P3候选，未实施）**：StateBackend虚拟文件树与ContentStore物理content-assets不互通；实际3次glob/ls无结果。澄清可读范围和file_ref含义，优先现read_content_export，不扩文件权限或新造通用FS。不是文件丢失证据。证据：neo-layout-continuation-review.md（1870–1954）。
- [ ] **R26-07 TOC刷新真实效果及非退化（P3候选，运行中待诊断）**：refresh_toc成功回执不证明页码出现；原新export渲染页hash相同，另一次fresh布局目录只剩标题/条目消失（2018公开观察），尚需终态独核。区分保存机制成功、字段实际变更及可读性；旧可用文件保留作防回退，不在运行中猜UNO根因或修模板。最终若不改善可诚实延期，不能强制采用坏的新版本。

证据目录：[本轮分析](../.analysis/synthetic-native-20261026-01/)。上述submit漏斗不是“全部错误”；后续按最终实际trace补齐，避免仅看最后状态。

### 本轮仍须核实（不是延期backlog）

- [ ] Co是否保存最终delivery/execution decision，选择哪些精确Word/Excel版本；文件存在/正确/可读与审核适用性一致。原1+6记录可按同task/snapshot/basis的scope聚合，不能把第二条单独说成7项。
- [ ] 新Layout导出不能自动继承旧export级审核；未变内容证据可按适用性保留。若确需新版本增量复核，不等于重做原Writer/七项Reviewer；任何在途host保护须安全终态再衔接，不热改。

### 仍保留的历史事项（需逐项复核状态，不能把旧标签直接当当前缺陷）

`.analysis/integration-baseline-20261020/system-baseline-plan/post-baseline-backlog.json`仍列4项：问题→原Writer修订→再次独立审核闭环；无需开发者介入的安全checkpoint恢复/预算衔接；按质量与成本共同评估上下文精简；审核目标/选材与实际工具能力一致及早解释不可执行范围。本轮局部恢复/完整材料包仅部分相关证据，不足以把上述总体能力全部打勾。


### 最新用户决定：呈现问题明确需要解决（2026-10-26）

Excel固定英文Note、Word正文/qualifiers重复呈现、技术定位的人读展示均为用户明确要求修复，不再以P3标签无限期后置。仍保必要限定、真实来源和底层追溯，按既定Trace→根因→职责→方案/验收→TDD→局部验证→回归流程执行；不在既有运行中热改。TOC另按实际复核登记，不能用坏新版本代旧成果。


### 本轮整改当前事实（2026-10-26，覆盖早期进行中记录）

- Excel固定Note标签已定向修复；同节点完整限定行精确去重已定向验证，表格/figure未渲染辅助text不参与删重，原mapping/限定不丢。
- 提交诊断54P；真实SDK下一请求收到missing body反馈。回执metadata恢复有summary+Store reopen+SDK与foreign负控，无新memory/自动语义通过。
- 四组真实UNO目录对照已完成：正确nested刷新及保存配置reuse刷新均有效；原顶层参数曾被忽略，现V4显式拒绝并报路径（原operation_id兼容保留）。并未改UNO程序。
- 重复读取仅新UUID时原反馈遗漏已1F→30P定向修正；仍只反馈，不声称通用停机问题解决。
- 七份提示词最终稿由实际DeepSeek CLI只读审稿中，尚未应用；当前源尚未集中全量回归，也未启动新真实轮。
- 最新逐片RED/GREEN及失败分类：.analysis/round-complete-remediation-20261026/verification-record.json。所有呈现问题纳入，不能以旧full03称当前源绿。


### Latest actual checkpoint: full02 and publication
- full02:3432passed/0failed/9graphsetupskip;2optionalcollectionmodulesuncovered. Neo exact audit accepted. Original374tests/645freeze/69protected unchanged at terminal.
- GitHub private aleph2/report-agent-system uploaded clean snapshot only, tag regression-20261026 / c1e7b649abc83826c7afb45f3e2225ee788a2ae2. No oldhistory/privatearchive upload; cleanclone full notclaimed.
- Fresh02 input-only prepare complete;50mstanding CAS applied preserving1915oldrows/46moldheld. Await Neo exact dispatch; no model called yet.


### 2026-10-26 post02 bounded repairs
- [x] Native receipt binding26P; artifact feedback48P; explicit query context14P; reviewed prompt contracts73P; Writer/reference existing94P + new2P. Neo slice review receipts in `.analysis/round26-native-followup-20261026`.
- [ ] Current-source frozen full (prepare active); no old full claimed as current.
- [ ] Fresh03 actual Co autonomy/Reviewer/Office/Trace, standing50m, unknowns preserved; one terminal email after Neo.


## 2026-10-26 fresh03 closure repairs — current evidence
- [x] Preserve03 terminal/Trace/mail receipt; original DB/old ledger/unknowns untouched.
- [x] TDD additive root/candidate diagnostics; actual SDK next-wire and strict refusal retained.
- [x] Reader-v2 annotation print repair; native Chinese and wide-Latin before/after, all text/coords/mappings preserved; overheight explicitly unverified.
- [x] Two actual DeepSeek reviews; exact five managed prompt changes, full-layout TOC preservation and executable Reviewer units.
- [x] Final targeted103unique passed, no failure/skip;389 prior test-area hashes same.
- [ ] Neo final current-source/full manifest review.
- [ ] One current frozen full01 (collection underway; no green claim).
- [ ] Fresh04 same fake inputs+real autonomous Co, standing50m; no runtime/budget amendment/dispatch yet.
Evidence: .analysis/round03-closure-repairs-20261026/plan.md and targeted-final-union.json.


### Round04 repair checkpoint — 2026-10-26

- Work-units-v1 reuses native todos/checkpoint; actual SDK schema/system/tool/source checks passed. Final affected/full checks pending. Evidence: `.analysis/round04-closure-repairs-20261026`.
- P2 existing V4 root delegation interruption recovery: retained failing reproduction and original reservation safety tests; direct same-child SQLite checkpoint retention is verified separately. Product root resume remains unsupported, not a passed recovery claim. Neo disposition `neo-reopen-reservation-disposition.md`; no unknown release/replay.
- Summary temporal subset/current-state labels and concise interpretation fix: targeted23P, genuine original2F retained. Artifact/method claim clarification does not add Excel visual obligations. Semantic behavior awaits fresh run.
- New confirmed gap: changing summary prompt changes failure key and can bypass a prior unknown outcome. Fake model reproduced second invocation; fix pending Neo minimum-boundary decision before full regression. No real retry occurred.
- After full regression and Neo review, tag exact tested source, then continue iteration under standing50m/round authority; tag does not mean engineering acceptance or close listed limits.


### 2026-10-26 full01 outcome and full02 containment
- [x] 94 affected tests passed after work-unit and summary-scope fixes; actual SDK prompt/tool provenance covered.
- [x] Full01 complete:3540P/1F/9setup skips. No missing/duplicate tests, all source/protected hashes unchanged.
- [x] Preserve original cancellation-test failure; owner-WSL read proves selection committed. Isolated original test1P, controlled delay1F; original5s and assertions unchanged.
- [ ] Neo-reviewed runner-only prototype-module isolation, full02 complete3550-node regression; do not call green before actual result.
- [ ] After actual fullgreen+Neo, publish exact sanitized snapshot/tag regression-20261026-round04-fixes; then continue fresh05.
- [ ] Fresh05 fake-only customer inputs and oracle reused; optionalwork-units-v1 flag, high/high600s and standing50m; no runtime case/budget/model started during repair.
- [ ] Existing V4 root-checkpoint reentry limitation and semantic/presentation checks remain explicitly open; child recovery test is not root recovery proof.


## Full02 and publication complete — 2026-10-26
Same frozen source full02: 3541 passed, 0 failed, 9 environment setup skips; two optional collection modules remain uncovered. Neo independently accepted all phase/JUnit coverage and frozen/protected hashes. Sanitized commit 60fd954cdcd660283d28bc7e773e435bd467ab32 tagged regression-20261026-round04-fixes and remote main/tag/peeled SHA verified; old tag preserved. Publication receipt: .analysis/github-release-20261026-round04/publication-receipt.json. No original private development history or runtime data uploaded. Continue fresh05 preflight, not yet dispatched; no semantic or engineering sign-off inferred.


## 2026-10-27 R06共同运行机制与可靠审核——当前仅计划

承接tasks/plan.md本日R06段，逐片详单见../.analysis/round06-reviewer-rootcause-20261027/improvement-plan.md。所有实施任务未启动，不能把此前全量通过算作这些改进完成；历史项保留。

- [ ] R06-P0：核共同机制、四角色prompt/权限与任务上下文边界；列清模型/effort待决。
- [ ] R06-P1（P0后）：先RED再修现工具状态两轴、兼容与实际SDK。
- [ ] R06-P2（P0后）：首错→保存回放及正负语义样例/标签，不运行真实LLM。
- [ ] 检查点：Neo确认P0基线及P1/P2预期证据，无新增固定业务流程。
- [ ] R06-P3（P1/P2后）：按薄片实施最小Reviewer与Co职责/判断修复，保留原接口和测试。
- [ ] R06-P4（P3后）：相关回归；实际prompt diff由DeepSeek审，Neo核最终SDK和技能动作。
- [ ] 检查点：Neo复核全部改动完成、定向结果和未决项，再进入一次全量。
- [ ] R06-P5（后续执行指令）：最终同源全量后，新独立fake+real自主协作，检查真实证据/结论/Office/Trace/tokens；失败先根因。

R06验收补充（未执行）：P2独立fixtures+827时序；P3落源前审具体prompt；P4核精确应用；P5派发前核600s/恢复/used+held/现存ledger/owner-WSL。

## Backlog：用户新增三项（2026-10-27）

来源：用户明确要求登记。状态均为待规划/未实施；本次登记不授权新增模型、测试、报告、数据库迁移或技术选型。保留已有待办和证据。

- [ ] **BL-20261027-01 — Optimizer的接入。** 在现有Optimizer实现基础上设计接入统一运行合同的方式，明确与报告Agent、学习worker及bounded工具的边界、权限、预算与验证。用户指定后置，不纳入当前最小修复；不把现有独立构图视为接入已完成。
- [ ] **BL-20261027-02 — 对报告依赖的资料构建RAG。** 评估资料/标准的检索与引用方式，保留来源、版本、定位和访问权限，并定义检索质量验证；检索命中不自动等于事实成立或审核通过。先设计，当前不引入服务或迁移资料。
- [ ] **BL-20261027-03 — 数据库设计问题。** 评审业务数据、检查点、Trace与独立财务记录的存储/生命周期，以及事务、并发和I/O边界；依据证据决定是否调整或更换数据库，当前不预设选型、不修改或清理现有数据库。


## 2026-10-27 两条主线实施进展（定向验证阶段）

用户已批准实施公共机制与第六轮审核修复；先测试再改，保留原测试，暂不重跑报告。Main负责实施，Neo监督复核；本批具体提示词已实际DeepSeek headless审后按Neo字段修正合并，不把审稿同意当行为通过。

实际范围、各次产品RED/fixture错误/收集错误、GREEN、技能动作及限制见[实施与验证记录](../.analysis/unified-r06-implementation-20261027/implementation-and-verification.md)。最终关联组以affected-final02.json及Neo最终复核为准。733基线原文件无丢失，原测试未改，精确检查见source-and-checks-audit.json。

已实施typed渲染事实、summary主体与模型服务分离、默认host模型/client所有权、CLI隐式fresh完整V4合同、Co/Reviewer/审核basis受审输出要求及文档边界。Writer/Layout提示词与角色模型/effort未改。SR1–6自包含样例用于后续语义校准，shape/SDK装配绿不等于自主审核改善；目前未做全量或真实报告，root透明重入与Optimizer/RAG/DB保持后置。

最终定向结果：关联组184P，最后CLI省略旧mode兼容补验17P（分批，不合并为201同源）；原测试零改动，未全量/报告。精确版本/首次失败/Neo结果见上述实施记录。


## 2026-10-30 全Agent自解释业务消息重构（仅计划）

共同原则已由用户确认；下列代码/验证任务未执行。Main写、Neo独审，不开新branch，不改highway；提示词/实际输入差异单独审核。

- [ ] D00 全角色/全部现有操作清单及字段合同、技能证据台账；依赖/范围/未决完整。
- [ ] R10 Reviewer内部证据兼容写入真实ReviewRecord：RED/GREEN、旧记录/事务/证据/负面/版本。
- [ ] R11 校验/状态/交付/复用直接消费者闭环；不只验证能保存。
- [ ] C10 复用Co字典/适配，实际task→ToolNode→原binder，权限/身份/版本不变。
- [ ] RC20 Reviewer平面消息真实入口、字典版本/后续读取/恢复；单check先闭合，不暗删旧复杂能力。
- [ ] I20 实际system/说明/schema/字典/返回/错误差异审核，提示词最小改动另审，未批准不启用。
- [ ] V20 原历史用例fake+真实LLM对照及真实记录/下游，指标和质量一起验。
- [ ] W30 Writer逐业务薄片接入，正文/来源/关系/表格与旧消费者兼容。
- [ ] L40 Layout逐能力接入，内容只读及导出/视觉/版本边界。
- [ ] E50 experience_optimizer通信接入（先明确原模块所有权），不改学习/发布策略。
- [ ] A60 全操作覆盖清单关闭与跨Agent恢复/交接；公开旧兼容和未迁移项。
- [ ] F70 新同源完整回归：ONNX例外单独、其余五片，Neo核全部节点/phase/JUnit/hash/skip。
- [ ] F80 完整fake OCR+真实LLM、独立Reviewer/WordExcel/终态与overhead验收；全量提交/tag。
- [ ] EXT 后续扩展规则的具体开发约定差异审核及合同一致性自动检查；未实装不得声称CI强制。

完整依赖、验收、技能动作与证据要求见tasks/plan.md“2026-10-30 全Agent自解释业务消息重构计划”；所有勾选须附具体版本/命令/结果/限制及Neo处置。

## 2026-10-30 fake02连接失败与断点恢复（用户认证邮件09:37 UTC）

- [ ] P2 视觉HTTP观测归属：vision/store=None与外层writer/coordinator不继承同一scope，成功与失败视觉均缺HTTP阶段；应复用现有观测上下文，离线验证角色/连接阶段记录，不记录图片/凭据、不改变重试和预算行为。阻断精确网络根因判断，不单独阻断有边界的验证；Main负责，修复另经Neo审核。
- [ ] P2 计时口径：同一失败调用单调583.004秒而事件墙钟约601–602秒；保留两种原始时间，查清差异，不把18–19秒猜成DB或协调开销。阻断精确overhead分摊，不阻断口径明确的状态报告；Main负责，先离线复核。
- [ ] P2 受控重试需求：用户要求有重试机制。先复用SDK/transport/model_recovery已有能力，核当前host为何SDK/connect=0、policy=None；区分已证未发送、明确错误响应与结果未知。重试须独立attempt、沿用同轮额度/权限、记录原因并保留原unknown/held，禁止多层重试叠加或盲目重放。当前具体供应商/代理原因待验证，不能写成已修复。
- [ ] 断点重启（当前执行事项，尚未验证）：用户已要求恢复；先核fake02真实checkpoint、已终态Writer子任务、已完成视觉与后续任务能否继承。保留原873.312秒失败终态及858925 used/2000000 held，本轮续跑不重置为新1亿；不直接再run只接受fresh的旧host、不从头重算、不清历史错误来绕过准入。Neo审核实际恢复方案，若入口不支持，先给出精确阻断及最小离线验证，不宣称已经续跑。

证据：`.analysis/all-agent-data-dictionary-plan-20261030/fake02-latency-analysis01.md`、`fake02-latency-public-evidence01.json`、`fake02-terminal-review01.json`；新指令原文/来源核验：`.analysis/task059-mail/received-1a18c2b7bf31a8ba.json`。只新增本节，原任务与证据保留。

09:53 UTC用户补充：恢复须从失败点开始；不确定时可“修为可确定 / 重新起一轮”。现有27P只证Co可接收原Writer不能恢复的反馈，不证原Writer失败点续跑。本项仍待修复验证，Main停止Co级continuation候选，按用户新轮方案准备独立03，复用已过全量产品与原宿主机制；原02现场/未决保留。见`fake03-authorization-preparation01.md`，未声明旧case恢复成功。


## 2026-10-31 LLM与传统信息系统的数据边界（用户确认，后续设计）

- [ ] **P2 — BL-20261031-DATA-BOUNDARY：统一消息与读取接口的封装原则。** 用户确认：扁平key-value和读取方式问题，都是传统信息系统与LLM驱动Agent系统之间的数据边界问题。LLM负责业务语义、内容选择和判断；程序负责依据服务端scope/记忆补齐身份版本、组装持久结构、解析存储类型、编码、分页、权限与完整性。内部数据库结构、JSON物理路径及空路径/字符串根值的实现分支不应成为模型完成业务的前提。字段具有清晰业务含义，不强加庞大通用格式；不要求每个key重复Agent前缀。
- [ ] **实际失败样例纳入后续验证：** 本轮Writer调用read_tool_observation时field_path=[]，目标analyze_source_image结果根值是object，触发OBSERVATION_FIELD_NOT_STRING；省略field_path后原始JSON文本读取成功。既有schema明确字符串路径，但错误只给码；既有拒绝测试不等于封装易用性完成。应先核真实调用用途，再提出业务引用/内容选择的最小合同，复用已有存储与校验，不自动把[]改为省略或猜测字段，保持各视图offset语义与原文身份。
- 当前影响：一次读取纠错及交互开销，未证数据损坏；不阻断当前报告。当前仅记录，不改在途代码/提示词，不新建通用数据框架；具体方案、实际LLM输入与schema变动先经Neo审核，按用户要求再实施。

证据：`.analysis/tag-rollback-real-20261031/observation-empty-path-rootcause.json`；Neo已只读复核直接触发与错误反馈边界。与此前全Agent数据字典方向合并考虑，不重做已验证的消息实验。


## 2026-10-31 600秒有限重试与新轮真实报告（用户已批准执行）

- [x] 原文与实际值核对：600秒/每次，首次+2次，独立200m used+held；不设额外4次/8m子额度，旧未决保全；邮件保持停止。
- [x] 产品RED02 19F；修复后关联组159P；精确生产host SDK/Mock四场景4P，含普通视觉耗尽后Co可继续与direct/wrapped fatal拒发。
- [x] 独立alignment核实际diff、测试与193sourcepins；原P1关闭，wrapped边界P2由此精确host隔离。
- [x] 唯一零模型stage：run03独立input/source/case/finance；旧canonical4114+旧shared500全表与文件摘要不变。
- [ ] 零模型prepare完成、Neo精确host/prepared/source/预算审核、唯一detached启动与真实进程核验。
- [ ] 最终独立Reviewer、来源事实/计算、同版WordExcel、可视排版、全量用量/未决与清理实核。

Main仅改model_invocation deadline回600、model_recovery已有策略参数化、deep_models同步active拒发、deep_runtime子任务超时观察；保留现有source binding修改，不改提示词/角色模型/effort，不开branch/commit/tag/push，不恢复邮件。首次RED及host01/02的测试夹具错误均单列保全，未宣称通过。完整计划与技能实做/版本、命令、测试、限制和Neo处置见`.analysis/restart-600-20261031/plan.md`、`verification-record.json`及该目录下stage/prepared记录。


## 2026-11-01 两文件提示词代码回归
- [x] 清空实际五个角色文件并验证空文件/非空canary/原生harness的唯一来源；作者原稿保留。
- [x] 首轮完整五分片终态核验；更新旧消息格式测试，保留业务校验。
- [x] 修复根级错误反馈与来源审计遗漏，局部回归33通过。
- [ ] 冻结新全量通过，核完整节点、输入未变和跳过范围，Neo复核。
- [ ] 同合成数据的DeepSeek提示词真实LLM轮及Word/Excel内容/排版验证。
- [ ] Codex提示词独立真实LLM轮、同口径质量/成本比较与限制说明。


### 2026-11-01 完整空提示词回归终态与 DeepSeek 验证准备

- 当前完整候选 `empty-role-regression-20261101`：3879 个唯一节点，3870 passed / 0 failed / 9 skipped；55 个串行节点及五分片 765/765/765/765/764 全部 exit 0；missing/incomplete/errors 均为空，1204 项文件 pins 不变。五个实际 agent Markdown 文件在本轮均为 0 字节。前两轮失败/中止结果保留，不拼接为本轮通过。
- 限制：9 项真实图/本地 embedding opt-in 测试未启用；GEPA/DSPy 两个可选模块因缺依赖于收集阶段跳过。不能声称这些集成已验证。
- Main 记录 Neo 独立结论：实际大小写敏感节点 Counter、phase JSON/JSONL、JUnit 完整一致，当前文件全集及逐文件 SHA 与 pins 相同；权限、原样采纳、来源重读、调用次数、源字节、unknown 与隐私断言保留。代码门槛允许继续既有授权的假数据加真实模型验证；不是精确运行的 launch 批准。
- Main 原样复制 DeepSeek 最终五份稿件至唯一 `src/report_agent/rules/agent-*.md`，与既有 comparison-verification.json 的五个 SHA 完全匹配；未改写候选。证据 `deepseek-candidate-activation-20261101.json`。随后进行已填稿的来源/native SDK/委派与 Git 恢复定向离线验证，真实模型尚未启动。
- 阶段技能：复用同版 TDD、debugging、Ponytail 的最小修复和保护业务断言验证；重读 using-agent-skills、git-workflow-and-versioning 0.6.13、Langfuse SKILL 与 prompt-engineering/create-dataset references，分别用于阶段识别、限定文件提交、输入/预期分离与对比条件固定。仅应用本地评估方法，未连接或上传 Langfuse、未优化或重写候选。部署复用既有 Git archive/stage/prepare/launch；不创建新分支、运行框架或计量机制。
- Git diff --check 的默认 CRLF 报告经命令局部 `cr-at-eol` 识别后无空白错误；未修改全局 Git 配置或批量格式化。

- DeepSeek 填稿后定向离线检查终态：90 passed，0 failed/skip，256.23 秒；实际 two-file/native SDK、委派提示词分离、来源捕获与 Git archive 恢复均通过。JUnit: `.analysis/deepseek-agent-prompts-20261031/deepseek-filled-source-check-20261101.xml`。这是加载/代码行为证据，不是模型质量证据。


## Stage 1 9a (2026-11-10)

Owner acknowledgment in substance includes the four corrections and a–f split. Parts a and b are accepted; main is fdf8f93. C is in progress. B2 follows c acceptance from main and must finish before paid Fake03. Reuse the current branch, with a separate size/verification record, tag and owner review for each part. Keep earlier unfinished history unchanged.

- [x] Record the four corrections and the draft-first split in the proposal, entry, consolidated handoff and first-report procedure.
- [x] **9a-a1 — binding contract.** Add applicable object/indicator page bindings and source eligibility without falsely confirming extracted values. Likely: planning_assertions.py, assertions/schema/kinds.py, actions.json, checks.sql and focused binding contract tests. Verify accepted versus wrong/unconfirmed binding and unchanged C4/C5.
- [x] **9a-a2 — access/extraction adapters.** Likely: writer_fact_packet.py, writer_assignments.py, assertions/evidence.py, writer_assessment.py and focused packet/extraction tests. Verify exact quote resolution, unknown-versus-absence and preserved qualifiers.
- [x] **9a-a3 — one owner checkpoint.** Likely: commission_plan.py, commission_assertions.py, issue_authority.py and focused checkpoint tests. One versioned sheet/reply produces all confirm acts; an interrupted fan-out redoes only missing acts with the same identities, no extra click or approval of later-added bindings.
- [x] **9a-a4 — retire the file approval.** Likely: source_use.py, current source-access/export callers, relevant source-use UI/action and source-use tests. Fresh-case planning sees supplied files; Writer/report access follows page bindings and case/C4 scope. No file-level wait or hidden source-approval export dependency. Preserve historical decisions and budget authority.
- [x] **Review/tag 9a-a.** Check actual source/check/fallback size figures and focused integration; accept before b.

- [x] **9a-b1 — disclosed draft assembly.** Likely: system_assembler.py, assessment_projection.py, risk_scoring.py and unscored assembly tests. Render every open row with its real reason and no adopted score/level; admit provisional drafts honestly.
- [x] **9a-b2 — issue/export closure.** Likely: material_issues.py, content_export.py, content_workbook.py and issue-pair tests. All three planning conflicts have records, bindings/routes and one-to-one Word comments/Excel rows; no score invention or check weakening.
- [x] **9a-b3 — rendered output.** Use existing render/inspection facilities on the draft pair; verify pages, tables, TOC, fixed text, citations and internal-content checks. Keep files/snapshots/verification provenance.
- [x] **Review/tag 9a-b.** Draft support and rendered-page record accepted; formal release stays refused.

- [ ] **9a-c1 — touched receipt/digest dependencies.** Remove only dependencies touched by a, preserving completed business facts/qualifiers, image-delivery safety, producer binding and exact redo. Split any implementation batch to at most five likely files including tests; record precise consumers before removal.
- [ ] **9a-c2 — field/check inventory and refusal measurements.** Classify actual pre-Fake03 agent fields/checks against requirements or reproduced bugs and consumers. Distinguish retained O4/O5/later-part code from the paid run's active path. Deduplicate real tool refusals by actor/native call ID; measure genuine zeroes and keep missing measurements explicitly unmeasured.
- [ ] **Review/tag 9a-c.** Size figures and complete active-path inventory reviewed. No deferred reference/release cleanup pulled into this gate without an actual a-path dependency.

- [ ] **9a-b2 — spec-owned format.** Start from main after c acceptance; follow docs/reviews/stage1-9a-b2-format-spec.md. Data-only assessment rows, shared spec renderer, source/open-item comments, instruction-role citation exclusion, numbering/cosmetics, two guards, new pair/PDF/comment list and hashes, one full offline run, owner acceptance, then main. No implementation during c.

- [ ] **Paid Fake03 gate.** Accepted a/b/c/b2 and applicable offline/rendered verification. Freeze answer key and scope before launch. If numeric scoring depends on f, complete/review f first; otherwise label unimplemented numeric rules as capability limitations and do not claim numeric-grade certification. Request separate owner scope/cap approval. This checkbox is not paid-launch authorization.

- [ ] **9a-d — general typed references.** Replace JSON-in-text references and their readers in small batches; no backlink/proof object/joint transaction. General cleanup can follow paid Fake03. Focused redo/read tests, then separate size record/tag/review.
- [ ] **9a-e1 — case-target findings/release.** Typed case target and full C12 membership, exact frozen pair and independent Reviewer; no placeholder content assertions or C5 exception. Keep temporary release refusal until the replacement is accepted.
- [ ] **9a-e2 — plan-scoped waivers.** Scope by plan version/object/indicator and effective input references, not snapshot. Tests: typo-only new snapshot retains applicability; changed/new evidence or binding invalidates it; withdrawal invalidates dependent release; no changed score; release records waiver IDs used. Separate size record/tag/review of e before formal release.
- [ ] **9a-f — numeric rules.** Separate new calculator functionality, using a small table-driven acceptance for guideline thresholds/interpolation, larger total-versus-bench score and unknown required inputs. Existing weighted/sensitivity arithmetic is reused. Separate size record/tag/review; move before paid Fake03 only if the frozen scoring scope needs it.

Full regressions, model runs and real-report launches retain their separate explicit authorization requirements. No source originals, historical cases, ledgers, holds or unknown requests are rewritten/released.


Part-a full gate (2026-11-10): owner-authorized replacement on dfebc40 passed cleanly, 6,160 passed / 9 existing skips / 0 failures in 26m32s. Part a is accepted under the conditional decision; main fast-forward is authorized. The first failed run remains failed on record. Next: b, using the existing branch. Details: docs/reviews/stage1-9a-a-acceptance.md.

Part-b candidate (2026-11-10): native unscored draft assembly and the Word/Excel data pair are implemented. Word pages are inspected; Excel layout is outside scope per owner clarification. Main stays at accepted part a; no paid launch or part-b full run. Review: docs/reviews/stage1-9a-b.md.

Part-b reader fixes (2026-11-10): source 25cd16c; all five rendered-page findings addressed. Final six pages and 23 Word-comment/Excel-issue pairs verified. Authorized full run on 3f3493c failed (6114 passed, 61 failed, 9 skipped): omitted private fixtures plus cover-date/citation regressions and heading expectations. All failed cases now pass targeted rechecks. A clean replacement full run requires new authorization; main remains 5e6c2ee. Review: docs/reviews/stage1-9a-b-reader-fixes.md.

Part-b replacement full gate (2026-11-10): owner-authorized exact 2b55f6c passed cleanly, 6175 passed / 9 unchanged skips / 0 failures in 32m12s. All 6184 cases accounted once; all nine coverage floors pass. Automatic cleanup verified 1250 unchanged files, removed the disposable source copy and left zero test databases in run temp folders. Earlier failed run retained. Main stays 5e6c2ee pending owner acceptance of b; c and paid runs have not started. Review: docs/reviews/stage1-9a-b-full-verification.md.

Part-b owner acceptance (2026-11-10): accepted fdf8f93; main fast-forwarded to that exact reviewed tag. Main re-inspected all six final pages; owner personal visual review is not claimed. Carry pending-section skeleton role to d and Chinese reader-facing reasons/questions to the future frozen paid Fake03 key. Part c starts with its receipt/digest consumer trace and active field/check inventory on the same branch; no new full/model run. Review: docs/reviews/stage1-9a-b-acceptance.md.

Part-b rendered acceptance confirmed without reservation (2026-11-10): owner checked cover/date, TOC, citations, Chinese reasons/grade descriptions, open rows and the printed count of 23 issues. Batch numbering hierarchy, duplicate punctuation and source/PDF spacing into d. c remains receipt/digest cleanup plus the measured active field/check inventory; paid Fake03 still needs the later scope/cap approval.

Owner b2 sequence (2026-11-10): b remains accepted. Finish/accept c and advance main before b2 starts. Paid Fake03 requires a, b, c, b2 and the measured inventory. B2 owns the rendering cosmetics/source-comment/spec format. Two future guard tests are listed in c as planned with no claimed result. No b2 source edits, new branch/worktree or launch.

9a-c: authorized full offline regression COMPLETE at tested a70ab4d (6,179 passed /9 unchanged skips /0 failures,26m29s). Owner acceptance PENDING; main remains accepted b. B2 remains queued after c acceptance.


## Context fix — owner-authorized Step 1 (2026-11-11)

- [x] C1/C4 file additions/removals with requirements/readers.
- [x] Agent-path wiring and frame-receipt consumer census.
- [x] Visibility trace design using existing captures and minimal missing join.
- [x] Owner chose classifier removal; live pre-C1 checkpoint path traced in section 4a.
- [x] Step 2: retire pre-C1 live-history admission and obsolete rubric upgrade; preserve C1 owner waits and original records.
- [x] Neo/advisor review Step 1 before C1 implementation.
- [x] Step 2: C1 focused V1/V2/V6 after the Step 1 gate.
- [x] Steps 3–4: C2 inventory/review, then C2/C3 verification.
- [x] Step 5: owner authorizes one final full offline run.
- [ ] Steps 6–7: newly sized probe proposal and separate owner launch scope/cap.

Details: docs/reviews/context-fix-step1-20261111.md. Main/dispatcher, original records and financial holds unchanged.


Context C1 Step 2 candidate (2026-11-11): implementation and clean focused V1/V2/V6 complete (200 passed). Neo technical review cleared; owner candidate acceptance pending. Step 3 must compare stock C2 with the two existing clearers before implementation. Main/full-run/paid gates unchanged. See docs/reviews/context-fix-c1-20261111.md.


Context update (2026-11-11): C1 346f1ba accepted by owner; Step 2 complete. Same-estimator baseline and Step 3 C2 inventory complete; independent packet review pending. One full offline regression on accepted C1 is running under this turn's explicit owner grant, with automatic passing-data cleanup. No paid probe/main move/C2 runtime edit. Details: docs/reviews/context-fix-c2-inventory-20261111.md.


2026-11-11 owner turn / 2026-11-12 UTC completion: One authorized C1 full on exact 346f1ba finished 6,206 passed, 3 failed, 9 unchanged skips, 36m30s; all 6,218 nodes once, nine coverage floors pass (90.72%), 1,300 frozen files unchanged. Two stale SDK frame expectations fixed at a412688 (2 focused pass); two retired frame-access census rows removed at 3eeb5e6 (4 focused pass). Neo reviewed both as stale test/inventory defects, not product defects. Full remains failed and evidence retained; no replacement full started. Step 3 C2 inventory independently reviewed after keeping task offered and marking catalog trimming separately scoped. Source/config unchanged; C2 remains unimplemented, main 7da4f94, no paid calls/hold changes. Records: docs/reviews/context-fix-c1-full-20261111.md and context-fix-c2-inventory-20261111.md.


2026-11-11 owner decision / 2026-11-12 UTC verification: C1 corrections accepted; C2/C3 implemented on codex/stage1-9a. Owner dropped catalog filtering. Source +60/−163 (net−103), if-guard predicates +5/−22, raise delta0, no new fallback. Shared stock policy clears only frozen qualitative rows and non-Reviewer immutable indexes; source wrappers proved mutable and remain excluded, so Fake03 Coordinator cost stays~3.36M. Prose supersession opportunity91619 proxy (~2.1% overall), no custom edit. C3 fixed read allowance's changing system prefix via existing tail, three-read allowance unchanged. Frozen3be0413 clean focused289pass/0fail,19modules,152.94s,1311files unchanged,57fixtures verified, automaticcleanup0DB; original c4bfee8 focused288pass/1fail preserved, Run06 fixture now selects actualToolMessage.151-call replay: Reviewer533952→423062, total4.362M→4.255M proxies (−2.4%),27 byte-prefix groups stable. V7summary fires at174842stored though edit-only163140<170000; trigger unchanged. Ten renamed functions/23cases individually mapped. No paid/full run, budget/hold/S2/dispatcher routing/main change. Review: docs/reviews/context-fix-c2-c3-20261111.md. Final full regression remains separately gated.

C2 pre-tag completion: retired-marker search reproduced two more stale visibility expectations and exposed a native callback false-pass (API returned last_error but test ignored it). Test-only corrections now assert exact visible slices/recovery and native terminal success. Final frozen6d4f813 focused run:341passed/0failed,23modules,206.29s,1311files unchanged,57fixtures verified, source copy removed and0temporaryDB. Twelve renamed functions/25cases mapped. f6f7050 afterward restores only unchanged original line endings in one test; AST identical. Runtime source remains c4bfee8; previous failed/full phases remain unchanged. Final record docs/reviews/context-fix-c2-c3-20261111.md; no new full/paid authority or main move.


2026-11-11 owner-local completion: Context Step5 CLEAN full on exact d0984f9/context-fix-c2-c3-20261111:6230passed,9unchangedskips,0failures,all6239nodesonce,36m50s. Coverage90.71%,all9floorspass;1316frozenfiles unchanged;57fixturehashesverified(51private). Automaticcleanup removed sourcecopy/all9tempdirs,0DB,exactprocessesabsent. Neo independently verified terminalaccounting/coverage/cleanup; Main ran tests. OriginalC1failed full remainsfailed and unchanged. No paidmodelcalls, budget/hold/S2/dispatcher/main changes. ContextStep5 verified; ownerC2/C3 acceptance pending, then Step6Coordinator-only probeproposal with scope/cap and separate launchauthority. Record: docs/reviews/context-fix-c2-c3-full-20261111.md.


2026-11-11 owner acceptance: C2/C3 accepted after code review and exact clean full6230pass/9unchangedskip/0fail. Main authorized to fast-forward from7da4f94 to reviewed6cf4193 plus documentation-only acceptance. ContextSteps1–5 complete. Step6 proposal recommends one Coordinator-only Fake03 planning probe, glm-5.3,5.5M cap, stop page sheet; cap/paid launch still pending. Ledger read-only06:24:50UTC confirms settled1991060/held1179648/available6829292,316attempts. Historical2Mhold unchanged. Parallel-call policy investigation and source text/receipt redesign deferred until after probe; no code/test/financial changes. Records: docs/reviews/context-fix-c2-c3-acceptance-20261111.md and fake03-planning-probe-step6-20261111.md.


2026-11-11 owner-authorized Step6 probe mini-planning-20261111-01 terminalFAILED beforepageSheet onaccepted2289ce1. GitHubpush succeeded/main2289ce1. GLM12paidcalls528712settled0newheld; runtime13logical includesblockednestedvision; turn12/1toolrefusal/58.292nativeSeconds/63.321wallSeconds. Offered analyze_source_image tried independentDeepSeekvision; scopedguard refusedSCOPED_REQUEST_WIRE_MISMATCH beforedispatch(0admitted). Publiclabel incorrectlybudgetReached and outerstatusplanning_stopped; originalsavedfailedresult preserved.0plan/pagebindings. All316oldledgerrows/auth unchanged,1179648holdpreserved, separatehistorical2Mledgernotopened. Neo confirmsP1capabilityexposure blocksunchangedprobe;P2labelsneedcorrection. No fix/retry/fullrun. Mainstaysaccepted2289ce1; resultonlypublication. Review:docs/reviews/fake03-coordinator-probe-20261111.md.


2026-11-11 owner decision: include existingdeepseek-v4.1-flash-1017 vision withGLM in nextCoordinatorprobe. DOCUMENTATIONONLY change list prepared:docs/reviews/fake03-vision-probe-change-list-20261111.md. Covers model-derivedauthorizedcatalog/staticall-toolcheck/sharedbudget, existingpagefactswithunknownunmeasuredfields, discovery-onlypaidvisiondescription, failurecode/profileID. Currentpartialtext-onlypatch+sidechatnormalization untouched/uncommitted. Proposed20Ksmoke requires completeinput/image/outputbound; current32768outputsetting exceedsit. Smoke/probe/fullregression eachremainseparatelygated; no code/model/ledger/configchanges inthisturn. Parallelreads/source-resultredesign deferred.


2026-11-11 owner revision/publication: vision change list now requires on-read image/vector bounding-box union coverage and explicit full-page-image/no-native-text structuralflag; no ingestion/store/OCR-quality-estimator additions. Hostvisionoutput8192 includesreasoning; visioncheck approvalmustquote boundedinput+image+outputreservation+margin(about40Kestimateonly), notdefault32768output. Staticfinalcatalogcheck and combined5.5Mprobe unchanged; all paidstagesseparatelygated. Documentation-only publication onexistingreviewbranch; main2289ce1 and uncommittedcode/test edits retained. Plan:docs/reviews/fake03-vision-probe-change-list-20261111.md.

## Context Fix Phase2, 2026-11-12

- [x] Steps1–3 offline measurements and answer-key review; private reports emailed.
- [x] Budget configuration/campaign amendment reviewed; existing usage and holds preserved.
- [x] Add AGENTS4.9 in a separate documentation commit.
- [x] Item1 atomic planning list backend, native schemas and current callers;175focusedpasses plus10diagnostic rechecks;Neo reviewed.
- [x] Item2 atomic binding lists/multiple indicators with whole-request replay identity;32focused passes,Neo reviewed.
- [x] Item3 whole small planning collection with existing version/observation limits;140focused passes,Neo reviewed.
- [x] Item4 Coordinator current accepted IDs;21focused passes including native tail,Neo reviewed.
- [x] Item5 record-local soft numeric-literal warnings and owner checkpoint display;173focused and111final overlapping passes,Neo reviewed.
- [ ] Offline full regression and actual-candidate replay comparison.
- [ ] Reviewed candidate tag and draft authorization preflight; satisfy standing-paid activation gates.

Phase2 first frozen full f7ad188 has confirmed P2 failures (middleware factory/type coupling and stale probe script counts). Existing assertions corrected in place;56focused passes,Neo reviewed. Original full retained as failed, still collecting terminal evidence; corrected frozen full/replay/tag/preflight remain pending. See docs/verification/context-fix-phase2/full-findings.md.

Phase2 additional verified instruction1a1d269b6649509c: compact model write replies and ready-item wording implemented;181focused/1native/55containment overlapping passes, no newtestfunctions,Neo reviewed. Full backend/audit data retained. Originalf7full terminalFAILED6262P25F9unchangedskip/6296once,37m14s;1341filesunchanged,193failedtestDBretained. Prepared85e full superseded before launch. Final compact candidate replay/cleanfull/tag/preflight pending. See docs/verification/context-fix-phase2/compact-write-results.md.

Phase2 latest follow-up: current-write-only short warnings/count-only receipt reader complete,24focused+16generic passes,Neo reviewed,no newtestfunctions. bb404full terminalPASS6287P0F9unchanged skips/6296once,38m43.5s,cleaned; retained as superseded launch gate. NEWcandidate same60comparison/cleanfull/tag/preflight still pending. See docs/verification/context-fix-phase2/current-write-warnings.md.

## Phase2 follow-up from verified instruction1a1d32e5cc228078

- [x] Deliver/review short excluded-binding and numeric-noise change list.
- [x] Deliver/review maintained paid full-flow entry proposal after the short fix list.
- [x] Implement approved bounded code fixes;184existingfocused passes,Neoreview;offline172to38recount;historicaloutputunchanged.
- [ ] Await promised fake-sheet confirmer decision; do not correct or confirm current sheet.
- [x] Select full-flow criteria-onlysubsection/rule-digest,routesfromapproveddecision,separate-stage import;nativeconfirmerattribution scope approved.
- [ ] Implement maintained full-flow entry/import extension, then native confirmer attribution within approved reply/schema/test scope; stop/report before wider changes.


Full-flow entry implemented in one new operator module, bounded business importer and native reply attribution; existing tests extended in place, no new test function names. SDK/offline HTTP verifies shared accounting/unknown hold/client closure. Historical sheet stays untouched pending confirmer. Source review/focused evidence and preserved correction failures: docs/verification/context-fix-phase2/full-flow-entry.md. Final frozen full/tag/preflight remain launch gates; no paid full report yet.


Full903448b retainedFAILED6285P2F9skip6296once;allhashes/floors/skipsverified. Approved one owning-package Commission.freeze_to API repairs assertion-boundary violation; optionalwarningrequirements-contract lookup repairsO6. Existing27+209 focused checks passed andNeoreviewed;counts overlap,nonewtestfunctions. Correctedcandidate requiresnewisolatedfull/tag/preflight; no paid or sheet writes. See docs/verification/context-fix-phase2/full-flow-entry.md.


## Fresh production entry — 2026-11-13

The fresh synthetic round and real cases use `report-run`, native `commission-reply`, then `report-run` within their own case. The old importer/orchestrator path is superseded for launch. Preserve its historical cases, checkpoints, decisions and failed/passing evidence. C helper separation is committed; production authority/budget and canonical Writer integration are the current candidate work. The single Writer catalogue entry is approved for the next slice; no candidate freeze/tag/paid run yet.

Deferred until the synthetic report is complete:
- stage handoff interfaces (export misses owner acts/receipts)
- harness touches internals
- move fake/probe harness out of the production package
- remove the superseded fake orchestrator run path after preserving its verification evidence
