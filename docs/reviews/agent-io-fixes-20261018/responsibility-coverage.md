# 44 项职责的验证覆盖计划（Neo）

本文件是覆盖缺口与下一步建议，不是新模型调用、原 batch1 重构或新增业务能力的实施授权。范围按 inventory.json 的 44 个 ID；它们不是 44 个脚本，也不需要逐项各调用一次真实模型。

## 当前证据与口径

本轮修复前选择集有 123 个唯一用例、121 通过/2 个 P2 红例；修复后的结果由 neo-review.md 另行签结。本轮四次真实调用：Writer 第一动作、Reviewer 第一动作、独立文字工具普通/缺料两个输出，结构均通过。不能将此扩大成四类职责完成，更不能称五类 Agent 全覆盖。

下表“已有”仅指已检查的选择集或本次四次实模；“骨架”表示仓库有相关测试可复用，不表示此次运行或通过。每一行都只给部分证据，未标注整项职责通过。C1-C3 的已确认新方案尚未实现；现有测试只能检查当前实际契约，不能手工注入新字段后宣称新方案已完成。

F=假模型/录制回放验证真实程序输入、权限、保存、错误、恢复；R=真实模型的动作选择/实质处理；A=真实保存对象或导出产物。R 不能替代 F，F 不能证明新模型选择正确。程序必要的权限、版本、预算、结构校验不是“干扰”。

## 可复用证据索引

- F1：test_agent_io_siblings.py，四角色 read_context/read_content_selection/search_sources 的下一模型输入；三角色 analyze_text/analyze_evidence 的真实材料/返回；精确读失败。已跑，部分路径。
- F2：test_agent_result_delivery.py，四角色 inline/offload 原文或精确恢复；Writer 限定信息/保存；Reviewer 未完成结论；Optimizer feedback/analysis 尾部。已跑，部分路径。
- F3：test_boundary_refactor.py，原始历史 I/O 回放、结果身份/完整性、历史授权比较、root TOC、Markdown 结构、文件系统 offload 及恢复。已跑，不是全部业务验收。
- F4：state-and-identity-v2 所列选择集，含 test_agent_io_identity.py、三项 task_supervision 恢复/补料/不重复任务、producer_observations 和 revision-input。18 项已跑。
- F5：artifact_io_lifecycle、summary_io_lifecycle；真实 SDK hook + MockTransport 的零派发/超时对照。修复前两项红，后续签结不得掩盖原失败。
- R-W/R-R：本次 Writer/Reviewer 各一个真实单步。未执行模型选择的工具。
- R-T：本次 process_report_content 的普通/缺料真实输入和 parser，未采用候选、未生成报告。
- 仓库骨架（此次未逐一重跑）：test_content_workbook.py、test_content_layout.py、test_layout_standard_controls.py、test_required_source_spans.py、test_bounded_review.py、test_artifact_review.py、test_learning_text_work.py、test_learning_feedback_delivery.py、test_learning_gepa_optional.py。复用前核当前活跃入口与 oracle，不恢复退役权限。

## Coordinator：8 项

| ID/职责 | 已有证据与缺口 | 下一步 F | 需要的 R 与 A |
|---|---|---|---|
| C1 理解委托及当前任务范围 | F2 证明部分当前输入，不证明理解；C1 新存储未实现 | 初始/恢复真实输入保留本次委托、终局目标、范围、要求来源；冲突/未决不被抹平 | Co 合成目标含局部动作与最终交付的区别；审实际行动/交接。A 检查当前已有状态，不虚构新 C1 对象 |
| C2 定义和维护验收准则 | 当前无真实 Co 准则样本 | 要求/原文到 Criterion 保存和下游传递；权限、空/矛盾输入；不由测试改要求迁就输出 | Co 生成准则，独立 oracle 核明确要求覆盖；A 逐字段核 Criterion，非仅 schema |
| C3 组织资料获取与工作划分 | F1 证明 Co 局部检索/分析 I/O，未证明全资料选择 | 全/空/读失败/partial 结果区分，材料 Ref/范围/局限不变；其他角色继续调查权限 | Co 合成跨来源任务选择合理调查；A 比对任务材料/来源与原输入，不要求固定选材顺序 |
| C4 委派并恢复原责任方 | F4 有恢复/缩 scope 拒绝；R-W/R-R 证明子角色首输入 | 任务→真实子角色→返回；首次/恢复/旧 receipt/错 owner/version；新 C1 上下文另标未实施 | Co 有意义委派；A DelegatedTask、owner、原生 checkpoint/receipt 绑定；不能以仅写 task 文本通过 |
| C5 定义审核范围与证据要求 | F4 有新料不能套旧完成；F3 有历史比较；完整范围映射未证 | 准则/check/scope/source extent 真实到 checker，漏项与超范围拒绝；旧 hash 不变 | Co 合成完整/部分/冲突要求；A 已保存任务与 checker 实际输入、后续 ReviewRecord 对应 |
| C6 消费结果安排修订/补证/排版 | F2 有 incomplete 结果可见；真实父决策未测 | 子任务已完成/部分/拒绝/未知原样到父输入，不升级“完成” | Co 接到明确缺料/格式缺陷后作适当下一步；A 原问题未被无依据关闭，无需固定唯一动作 |
| C7 冻结导出选择交付版本 | F3 有部分真实 DOCX；配对骨架另有测试 | snapshot/Word/XLSX/exact version、权限及文件失败，旧稿不自动变验收稿 | Co 选择何版；A 打开实际 Word/XLSX、SHA、关联和保留内容；至少一个完整业务样本 |
| C8 如实决定继续/等待/结束 | F5 涉及失败分类，不等于 Co 决策通过 | execution decision 与未完检查、unknown、授权状态不混；合法结束不误报 whole-report accepted | Co 缺料/预算/已完成三个情景；A 检查最终声明与真实对象/检查状态一致 |

## Writer：12 项

| ID/职责 | 已有证据与缺口 | 下一步 F | 需要的 R 与 A |
|---|---|---|---|
| W01 理解委托及策略 | R-W 仅正确先检索一步 | 当前委派/来源/准则实际输入；恢复不换 owner，不自动继承未提供的父对话 | Writer 含目标/限制合成任务；A 其调用实参是否承接要求，不把公开自述当完成 |
| W02 选择获取资料上下文 | F1/F2 有完整/延后精确恢复 | 正常/无结果/权限拒绝/跨页表/多源冲突/同义检索局限的显式结果 | Writer 根据材料逻辑关系继续查；A 选入工具的 Ref/范围，不把可访问当已读 |
| W03 委托提取比较解释 | F1 检查两类分析工具输入/输出，均 fake | 来源/观察/结果的组合输入，尾部限制、错引用及无关来源反例 | 分析工具合成比较，不需 Writer 重做整段分析；A 原始分析、局限与后继决策 |
| W04 决定结构粒度顺序关系 | 尚无真实结构选择验证 | contains/position、合法依赖、非法/跨 owner、结构提交和旧版兼容 | Writer 按给定章节/表样约束组织；A 真实树与导出结构，不固定唯一章节拆法 |
| W05 委托生成正文表格图注证据 | F2/F4 与 R-T 有部分生成/修订 | 原始完整标准/材料→真实 producer packet；body/schema/qualifiers/generation_notes；表格/图注/批次不同形状 | 已有纯文本 R-T；后补表格/图注/修订契约代表；A parser 及真实 payload，不把 JSON 合法当内容达标 |
| W06 采纳保存原始内容 | F2/F3/F4 有限定信息/身份/回放；真实采用判断未测 | 精确采用/篡改 body或qualifiers/错 receipt/未知/invalid/重复保存，明确延后字段按契约恢复 | Writer 对受限候选选采纳或重做；A 原始候选到保存对象逐字段对齐；不强制新增审核调用 |
| W07 保留来源计算推理关系 | 部分来源捕获骨架；本轮未证 term 与原值映射 | 引用精确版本、数值输入/计算 receipt/结果、错源值/错公式/缺值反例 | 工程来源适用判断仍需实质样本；A 已保存 Evidence/Relation/计算与源值逐项核；不以算术正确替代取值依据 |
| W08 调查反馈修订自有内容 | F4 有 revision packet/版本反例 | exact target/CAS/局部修订不重写无关正文、任务/owner限制、旧义务不消失 | Writer 修正一个明确问题且保护正确内容；A 修订 diff、当前依赖/准则一致 |
| W09 选择版本形成快照 | F3 部分 snapshot 路径，未覆盖全部 channel | 精确 refs、root、closure、跨版/无关成员/替换失败；内容/工作簿 channel | Writer 选择真实版本；A 快照成员与后续文件，冻结不等于审核通过 |
| W10 导出检查内容传递 | F3 验证 TOC/Markdown 等；未整份客户规范 | 原文图表/布局到真实 exporter，错误/receipt/版本；复用配对导出骨架 | Writer/Layout 选参数；A 实际 DOCX/XML/XLSX 与要求，比对不只与旧稿相等 |
| W11 判断经验适用并记录采用 | 尚无本轮端到端采用证据 | release/scope/版本/权限/失效经验可见与记录，不让经验覆盖用户/源事实 | Writer 适用/不适用经验对照；A provided/use/effect 分开，不以注入即采用 |
| W12 回报成果限制和转交事项 | F2/F3 有局部工具限制，不等于父交接全验证 | 正常原生子任务返回到父下一输入，真实 refs/未决/错误不丢，不手拼交接代替平台 | Writer 合成未完成任务返回；A 父收到的结果与实际对象/缺口对账；新结构化返回方案未实施 |

## Reviewer：9 项

| ID/职责 | 已有证据与缺口 | 下一步 F | 需要的 R 与 A |
|---|---|---|---|
| R1 识别审核对象准则必查项 | R-R 只选择 read_task_assignment；F4 有 scope 恢复反例 | 保存任务/准则/extent 到实际 checker；不允许空声明假完成，错误准则/版本拒绝 | Reviewer 从完整 assignment 选择检查；A 检查计划与原要求，不是只看首动作 |
| R2 调查正文关系原材料 | F1/F2 四角色读/恢复覆盖部分 | 正文/原源/分析观察在正确 snapshot/授权范围，partial/读失败可见 | Reviewer 对冲突资料进行调查；A 实际选材，不拿 top-K 当完整覆盖 |
| R3 固定独立调查来源版本 | 现有 required_spans 骨架，本轮未全跑 | source digest/ordinals/view/owner/receipt真实绑定；metadata binding 不冒充全文 | 不必每种机械版本错误实模；A 固定的来源版本与实际传入字节一致 |
| R4 组织实质内容审核 | F2/F3 有 fake checker 与保存；无本次真实 checker | check→材料→独立工具→parser→ReviewRecord；scope歧义/缺料/received-invalid/unknown | 独立 checker 正常/不足代表；A judgement、linked receipt、remaining_checks，审核完成不等于通过 |
| R5 获取实际文件结构观察 | 相关 artifact 骨架，本轮仅部分 F3 | 真实 DOCX/XLSX 文件读取、hash/版本/配对、解析失败和超范围 | 单纯读取不需实模；A 实际 OOXML/cells/段落、局限，不按预设表头位置误报 |
| R6 Word 页面视觉调查 | 本轮未证明视觉识别 | 页码/裁图/源参考/export绑定、失败/权限/错图；不擅自扩成所有Excel视觉 | 需要视觉能力时用真实图像小样本，不以文字模型替代；A 实际页图/receipt，不是渲染成功即版式正确 |
| R7 组织文件页面实质比较 | F3 部分 fake artifact；F5 NFR05 修复验收独列 | exact observations→独立 artifact checker→保存/缓存/缺页/零发送/未知 | artifact checker 合成可视差异代表；A 真实 paired pages、coverage 和判断 |
| R8 新版复查或沿用旧局部判断 | F4 明确新材料不得套旧完成；历史对比 F3 | 新旧版本/check/extent identity、受影响范围、合法沿用与非法关闭对照 | Reviewer 决定何处需重查；A 旧结论有效性与新版证据，不以所有旧评审一概无效 |
| R9 回报检查未完与执行问题 | F2 未完成判断保留；父消费未完整测 | saved ReviewRecord/HandlingRecord/失败在原生返回完整可见，known/unknown区分 | Reviewer 部分完成返回；A 父收到内容与真实 scope/check 状态一致，不靠完成话术 |

## Layout：7 项

| ID/职责 | 已有证据与缺口 | 下一步 F | 需要的 R 与 A |
|---|---|---|---|
| L1 理解排版目标参考边界 | F1/F2 只证明读取结果完整，无本次 Layout 实模 | 适用标准/内容边界/授权snapshot真实可见；无全量资料灌入 | Layout 合成明确格式任务；A 其参数依据，不以老稿等价当达标 |
| L2 核查可用排版能力 | 存在 content_layout 骨架 | 真实公开 schema/capabilities/非法参数一致，不能承诺不存在能力 | 可与 L1/L3 同例；A 能力缺口明确转交，不能隐蔽代换标准 |
| L3 要求转排版参数 | F3 部分Markdown/TOC；客户标准参数选择未测 | 给定参数真实生效/冲突拒绝/默认不掩盖显式要求，复用 layout standard 骨架 | Layout 生成标准对应参数；A margins/styles/1.5/table/TOC 等实际值与标准独立比较 |
| L4 生成应用参数Word | F3 单目录、Markdown结构部分通过 | root-only TOC、段落/表格/图像不丢、版本/owner/receipt/失败，实际 exporter | 不需每个 exporter 分支实模；A DOCX及原内容逐项核，成功导出不等于正确 |
| L5 获取文件结构渲染产物 | 渲染与视觉不在本轮证据 | 保存文件/页图/digest/读失败/过时render拒绝；渲染依赖单列 | 不需普通读取再加LLM；A 实际页图与文件结构，相应环境可复现 |
| L6 据页面观察判断调整有效 | 未有本次视觉/调整实模 | 观察/参数/版本准确到决策与新导出，无program替模型判视觉通过 | Layout/视觉工具具体职责小样本；A 调整前后实际页，不能只比较参数相等 |
| L7 回报排版成果缺口内容需求 | F2 仅公共I/O，不是完整子任务回传 | 原生结果refs/能力缺口/内容不可改边界到父，无新权限 | Layout 部分能力不足返回；A 父下一输入及真实export/未解决项 |

## Experience Optimizer：8 项

| ID/职责 | 已有证据与缺口 | 下一步 F | 需要的 R 与 A |
|---|---|---|---|
| E1 理解学习任务与反馈 | F2 验 feedback tail，非完整学习任务 | job/feedback/claim/scope/优先级真实进入，有界大反馈精确恢复 | Optimizer 合成有冲突意见任务；A 仅处理已分派内容，不自动跨客户学习 |
| E2 调查反馈与既有经验 | F2 feedback/analysis部分；学习测试骨架未全跑 | exact反馈版本/项目事实/策略/用户意见分开，外域读取拒绝 | 与 E1 同任务可复用，不规定工具顺序；A 实际检索/引用及调查边界 |
| E3 委托分析并采纳项目事实 | F2 analyze_learning_material 尾部通过 | 原材料→分析→fact candidate字节/引用/owner/receipt，策略不能伪装事实 | 学习分析工具不同契约仍需代表样本；A fact候选与来源/分析对应 |
| E4 形成策略及适用条件 | 本次未真实验证策略产生 | 输入/作用域/权限/状态不可程序扩大；模型策略字段完整 | Optimizer 提炼适用与反例；A 策略不是用户指令或原文事实，生成不等于有效 |
| E5 保存修订未发布候选 | 本次未执行对应骨架 | candidate/release/version、错域/改owner/重复写/撤销，不自动发布 | 候选字段可与 E4 同样本；A 实际候选状态，不能把保存当发布/采用 |
| E6 逐条反馈处置 | learning_feedback_delivery 骨架；本次未运行 | 每条 disposition及关联、部分失败/并发/claim，不能遗漏后标完成 | Optimizer 处理采纳/拒绝/待查对照；A 全分派反馈→真实处置关联，拒绝需理由 |
| E7 选择宿主授权 GEPA | 存在optional骨架，当前部分依赖/环境未核 | host授权/预算/可用性/请求范围，fake evaluator 验拒绝越权；不调用优化模型 | 普通职责覆盖不强制真实GEPA训练。若用户需该能力另案评估；A 授权/评估输入/真实结果，不替换成任意LLM自评 |
| E8 返回学习成果限制与问题 | F2 不等于最终学习回传 | 原生学习结束结果与候选/处置/未完/错误一致，失败不吞掉 | 可与 E1–E6 同一合成任务观察；A 父/宿主收到结果，不以candidate数推学习效果 |

## 下一批怎样执行：先少量共用场景，再补差异

1. **本批两修复闭环（正在执行，非新范围）**：NFR05/NFR10 红→绿，旧 placeholder、同/新 ID、真实发送后未知、伪造预算异常、取消、缓存与旧 Writer readmission 回归。程序分支用 fake/MockTransport 即可，无需新付费。
2. **先补 F 矩阵（建议）**：用现有 Driver/真实 ToolNode、临时 workspace、统一断言/参数化 fixtures，补 Co 父子交接、准则/材料到独立 checker、Layout 标准到真实导出、Optimizer scope/处置/候选；每项记录实际 nodeid/输入/结果。初步人工 2–4 个有效工作日；如果 fixture/历史测试契约有歧义，单列诊断，不为凑覆盖恢复错误旧行为。现有骨架可缩短，但不是完成承诺。
3. **产品对象/文件对照（建议，与 F 并行）**：选一个合成完整报告骨架，给定外部 oracle 的页边距/字体/表样/目录/原文图表及Excel cells，走真实导出与保存。约 1–2 个有效工作日，渲染环境/视觉能力缺失另列；不要把原稿复刻当oracle。
4. **剩余 R 小样本分波（仅建议，未启动/未新增授权）**：优先 Co、Layout、Optimizer、独立内容 checker；下一波补 artifact checker、学习分析、表格/修订契约，必要视觉另列。预计额外 6–10 个合成 HTTP 机会，每波最多 4 HTTP（含 SDK 重试）；失败/重试消耗本波额度，不自动补跑。准备/审输入输出约 1–2 个有效工作日，服务等待和模型失败不计为固定完成日。当前四例有效证据复用，不为凑每职责一次而重呼。
5. **一个完整业务样本收尾**：在 F 与小样本明确后，原用户目标仍需真实完整内容/文件与独立审核。该范围/预算/工期要依据届时报告状态和未闭合问题另定；不将当前四调用外推成全部模型能力，也不要求每次程序修改都重跑完整业务模型链。

这些人工区间是测试构建/评证工作量，不含发现产品问题后的修复、未实现 C1-C3/结构化任务返回、索引、学习新设计等开发。各步可重叠，不简单相加宣布交付日期。新增实模次数是下一轮候选上限，实际模型、输入、每请求已验证 token bound、累计账本与未知预留必须执行前再核；不以四例平均token线性承诺成本。

## 什么才叫本轮“覆盖核查完成”

- 44 行都有明确需求含义、当前真实入口、F/R/A 所需与所获证据、未实现/未验证状态；不能只记调用次数。
- 对实际注册角色/工具合法组合和被拒角色组合建分母；对正常、非法、边界、失败、重复/缓存/恢复列有限关键协议路径并逐项映射。尚未建立的分母不报覆盖率。
- 关键权限/版本/unknown/范围/结果分类复合条件逐项做独立条件对照；分支覆盖不冒充 MC/DC。MC/DC、无限循环路径和全部材料语义目前均未证，不因上表齐全就报100%。
- 必须分开报告“F 程序覆盖完成”和“R/A 业务证据完成”。测试可失败且覆盖事实仍记录；绿色数量不自动关闭已知错误或未实现职责。
- 每个新增缺陷保留独立反例、原失败与修后结果；合法历史比较、精确来源读取和 Agent 动态方法选择不能因测试简化被删掉。

完成上述核查后是否恢复原 batch1，由用户与Neo依据缺口决定，不自动启动。此矩阵不新增角色、固定语义工作流、第二任务库或统一测试平台。

## 对 agent-centric 测试的判断（本轮用户补充）

赞同以“智能体职责”为测试组织单位，以接口、路径、条件和状态转换为验证维度。职责回答“为什么测、输出给谁”，维度回答“哪些错误分支还没有证据”；不是以 Agent 替代所有模块单元测试，也不是把每个函数叫作一项职责。

建议维持三种清楚的证据：

1. **F：程序没有越界。** 给定明确职责、要求、材料与状态，用 fake/replay 经真实 native 边界核对实际输入、schema、权限约束、返回、保存和恢复。它要阻止擅自改意图/删限制/扩权限，也要证明非法输入被拒绝；不是要求程序对任意 Agent 决定都放行。
2. **R：模型在职责内选择和处理。** 合成材料真实模型探针看动作/参数/结构与事实限制，不只 schema。oracle 描述允许的结果集合与禁止事项，例如“应先获取未读必要资料，不得捏造分值”；不能只准 search_sources→read_source_page 的唯一序列。fake 的预排工具调用是程序测试驱动，不是对真实 Agent 的强制策略。
3. **A：职责产物实际正确传递。** 读真实保存对象、DOCX/XML/XLSX/ReviewRecord/候选，核对本职责承诺与用户要求；导出成功、模型自称完成、schema 合法都不能替代它。完整业务样本证明职责组合，不把各自局部通过直接相加为整报通过。

为降低复杂度，只沿用现有 pytest/Driver/native工具和实际产物读取：一组共享合成资料、少量参数化角色/入口、既有结果与 trace。矩阵链接到具体 nodeid/证据，不新增一套 Agent 测试平台、职责注册表、每个职责一个 runner 或强制业务工作流。纯机械 guard 用小单元测试覆盖条件，代表性端到端测试核真实装配，避免每个布尔条件都重复启动整套图。

新 bug 先归到已有职责与边界，保留最小独立反例并扩大必要的同类路径。只有确实新的职责/输入契约才增加新类别。测试的目的是让职责和程序责任更单一，不能通过固定合法方法、恢复退役权限或冻结错误旧行为来换取简单的绿色统计。

上述分层与现有平台方法一致：LangChain 官方经验分别讨论单步动作、完整回合的轨迹/最终回复/状态产物，以及按测试任务确定成功条件；它也建议复用 pytest 和外部 API mock/replay。这里复用方法，不引入 LangSmith 服务、不上传项目资料，也不把外部 API 录制案例说成现成的本项目 LLM 录制器。[Evaluating Deep Agents: Our Learnings](https://www.langchain.com/blog/evaluating-deep-agents-our-learnings)

精确轨迹并非普遍正确 oracle：官方文档明确指出可能有多条正确路径，单步也不能代表完整 Agent。因而只有授权/因果依赖要求的先后关系才强制，其余比较职责结果、参数与证据。[Application-specific evaluation approaches](https://docs.langchain.com/langsmith/evaluation-approaches)

## 修复确认与缺陷发现必须分开（用户本轮进一步强调）

本批 43 项定向检查的主要目的，是证明确认的两处错误已修且相邻保护不回退。它们不是一次独立的、穷尽剩余问题的发现性验收。大量绿色既不能说明再无缺陷，也不能否定这批真实红→绿的价值。

下一批先根据用户意图/职责约定独立定 oracle，再选输入，不能从当前实现的输出反推“正确答案”。优先选缺资料、矛盾资料、部分完成、旧结果不适用、错误恢复、角色之间交接等尚缺证据的组合；允许合理的其他行动和明确失败，不能为制造红例强迫错误动作或将不支持的新功能偷偷当现有义务。

建议只做少量有明确归属的 **test sensitivity** 检查，不建 mutation 平台：

- 历史/隔离错误版本，或在隔离测试边界恢复一次已知的“丢限定信息”行为：同一独立输入和断言应失败于具体信息完整性断言，不能仅因 fixture/import 异常而算“杀死”。
- 在临时隔离反事实中去掉“有真实 hook 拒绝证明”的条件：无 hook 的预算同名异常用例应抓住错误未派发分类；原 oracle 不变。
- 在隔离反事实中允许 artifact 新 ID 重开原 raw：当前同/新 ID、原 raw 不变/零新增发送用例应抓住权限扩张。隔离检查需有明确短超时和 HTTP 硬上限，不能真实调用，也不改工作树应用或历史数据。

这些是建议，**本轮尚未执行**，不预报 mutation score。先选 2–3 个关键不变量即可；若反事实未被测试发现，应报告测试盲点，而非据此认定产品已经触发该故障。真实缺陷发现不追求“必须几个红”，但必须诚实保留红例、未证范围和合法失败。固定期望后，不能随产品修改一起偷偷放宽；必要的 oracle 更正要给需求依据与前后差异。
