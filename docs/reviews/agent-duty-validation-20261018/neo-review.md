# Neo 职责验证独立审查（进行中）

本轮：Codex 执行测试/合成探针，Neo 审查职责、oracle、源码与实际输入输出。产品重构 batch1/C1 仍暂停。本记录是阶段证据，不是 44 项职责或报告交付的完成声明。Neo 未运行测试、付费调用或修改应用。

## 当前确认的程序证据

- 原 15 组现有测试：196 个 call 通过；optional GEPA 模块因缺少 dspy 被跳过，E7 不计通过。现有测试的选择不等于每条断言都已独立审查。
- 新增 18 个有限程序案例：父子角色两种 managed 配置的完整显式交接、Writer 显式 Criterion/SourceArtifact 的完整 Ref+payload 到文字工具、四种 Layout 参数到真实 DOCX、三类学习候选以及失败重放/部分处置终态。learning-third 实得 6/6；先前错误 schema 字段的 fixture 失败保留，不计产品 bug。
- DOCX 断言来自固定外部 fixture：25/25/25/15mm、Normal 宋体12pt、1.5 行距、表格内容和双线0.5pt。证明这些具体参数在真实当前导出路径生效；没有证明模型会自行从全部规范选对参数，也没有核完整客户格式或视觉效果。
- 学习组合中，保存第一条反馈的 candidate/disposition 后，第二条仍未处置；Agent 的“Done”不能使 host 完成 job，失败 job 也没有自动重放。这是有效的跨步骤控制证据，不是学习策略质量证据。

coverage.json 将 18 项职责标为其**明确列出的有限程序切面**最低代表断言已满足；不再把已证切面永久称未测，亦不把这些行升级为整项职责完成。

## 真实合成第一波：4 HTTP，不能按“1绿3红”直接数产品缺陷

目录：`.analysis/agent-duty-validation-20261018/roles-live-wave1/`。实际 runner SHA256 `f7420bcc92a10f087058c29db0e9df7aa5056d2fbc5c4e00166d23d0aa7db8ed`。保持实际 mixed services、完整 native messages/tools 和适配器，返回 Agent 动作只校验，不执行。

| 情景 | 已证事实 | Neo 判定及限制 |
|---|---|---|
| Coordinator 收到 Reviewer partial 后的下一步 | 1 HTTP；finish_reason=length；content为空，无 tool_calls；output8192，公开 usage 的 reasoning_tokens=8192 | 本次人为8192上限处未产生可判断动作；不能判其将 partial 误认接受，也不能算 unknown。增加上限不保证成功，尚未确定为何没有及时给出动作。 |
| Layout 已读 capabilities 与 snapshot | 1 HTTP；生成 export_content_snapshot；边距和行距正确，但把 qualifier_placement 放在 layout 根级 | 本次模型参数构造非法。wire36个工具与 native schema 全等；根级无此字段且 additionalProperties=false，nodes.items 才有，capability 返回也写明 per-node。当前不支持程序丢字段/改层级的归因。验证器正确拒绝，候选未执行；不能去掉额外字段后声称原样通过。单个样本不能证明稳定系统性根因。 |
| Optimizer 已读 before/evidence 后的下一步 | 1 HTTP；read_learning_feedback({}) 参数合法 | 有限结构通过。该动作可能获取尚未取得的 correction/元信息，不因“又读反馈”就判无意义重复。未执行其所选动作、没有候选/处置闭环或效果结论。 |
| 独立 checker 面对70与75–100冲突 | 1 HTTP；收到 response，finish_reason=length、output8192且 reasoning_tokens=8192；实际 parser 抛 EVIDENCE_ANALYSIS_EMPTY_RESPONSE | 本次没有可采用审核结论；正确保留收到但不完整的原始响应，不能当零派发、unknown 或真实“不满足”判定。此 probe 的统一8192上限不足以给出本样本的行为证据。 |

只使用公开输出、工具调用、schema 和 usage 元数据；不以模型私有推理文本解释原因。Coordinator/checker 的本次直接终止条件已知，内部为何耗尽上限尚未知。两例是 **R 证据未取得**，不是两个已证应用 bug。Layout 是有效 R 失败样本，应用层校验表现正确；根因到当前输入模式/模型稳定性的归因仍待证。

本波4次响应累计86,705 tokens；账本实记93,374,900→93,461,605，26m旧 holds 保持，170m授权保持，可新保留50,538,395。runner 的旧行比较与代码 during 检查均 true。Neo 已核原始 result 和实际 wire，但尚未另做账本逐行数据库复算。本波不补齐、不重跑；仍在总12 HTTP边界内，下一波先根据场景和模型配置确定合理输出界限，不能把统一8192当所有角色的自然能力上限。

用户随后明确给本轮验证/测试10m上限；86,705计入，余9,913,295不是必须用完。原170m/26m历史不变；不自动追加总授权。Neo 同意测试runner使用固定1032原行基线、逐新增行已用+未知上界、整波4×已核最大2m bound的保守准入及同phase文件锁，继续受原TokenBudget/HTTP cap保护，不建双账本。实际新runner和预算临界反例尚待审，不以设计同意当已具运行约束；详见 neo-plan.md 最新限定。

预算 runner 已读审：`phase_admission` 比较旧行和 authorization，全体新增行已用+未知占额，已有 bound_violation 拒绝，12条新增 reservation 保守上界；FileLock 覆盖预注册和 await 整波。`phase-budget-offline` 5/5实得通过，覆盖等号/+1、未知占额、原行漂移与次数上限，符合所列判据。新增行数可能含 known_not_sent，不应称其精确已派发 HTTP 数；它在此是保守上界，实际HTTP另记。

发现 **H-PATH-01（P3，仅测试harness，启动前已修）**：首版 validation-budget-authorization.json 的 baseline_ledger_rows 使用反斜线，WSL PosixPath 的 ROOT / 字符串不能把它解析为目录分隔符；会在读基线时0HTTP失败。只把该相对路径写为正斜线并保持基线文件/hash/1032行/授权含义。实际WSL `phase-budget-preflight.json` 已核路径resolved、原1032行保留、已用86705/新增held0、第二同phase锁被拒；authorization SHA `9f2d8316d5fca1cb216172af8f6a0848d60ee101090ee6b6af2dae364e0aa081`。不改应用/平台、不归为报告产品 bug。第二波offline4/4及65536配置/实际parser通过后，Neo才批准一次4HTTP。

## 真实合成第二波：四个结构合法，业务证据不同

目录：`.analysis/agent-duty-validation-20261018/contract-live-wave2/`。实际configured输出界限65536，未降低strict/切换服务/裁工具。Co和checker明确关联第一波已收到的length响应；本次是纠正probe容量限制，不重放未知、不改旧失败状态。

- **Coordinator**：51tools与native-input全等，partial子返回250字符完整送达。产生公开的“调查当前状态”说明及 `read_decision_state(path=['assignment'])`。结构合法，但当前Co System没有 assignment 字段，只有 review_tasks 等已提供路径。`decision_state.read_state` 对该路径会抛 STATE_PATH_NOT_FOUND；本波没有执行所选动作，因此不能说完成了合理状态读取或处理了partial，也不能报错误接受整报告。通用工具description确实以assignment作示例，可疑可发现性不足，不由单样本确定程序根因。保留真实动作作下一组offline错误→正确路径测试。
- **独立checker**：actual packet有完整Criterion、claim“class B use70”、source“B permits75–100”及结构上下文，三个已选证据版本绑定。text-tool-input与wire两消息逐字相等。公开raw判 `completed/not_satisfied`，明确70不在75–100、真实class仍可条件化、root正文未审；parser保留逐check observation链接并在临时workspace保存ReviewRecord。证明该简单合成矛盾的本次实质判断正确，不是原报告审核完成。
- **表格producer**：一条实际selected source完整列出两个表头和两行；wire与tool输入全等。raw完整payload与parser payload相等，kind=table，列 `Class/Permitted score`、行 `A/50–74; B/75–100` 逐项一致；没有选分/虚构总计，并如实保留“原文表说明可读、物理页未定位”的限制。只证明这张简单合成表，不推及复杂合并单元格或指南完整表样。
- **qualifiers-only**：actual schema只准qualifiers，exact target Ref/digest/原始table payload都进入packet；wire与tool输入逐字相等。raw只留technical=Weathering class not established，旧process备注删除，技术未知未丢。服务端合成的body/kind/claim_kind保持，旧对象未采用/改写。不用“body相等”掩盖限定词语义；这次两方面均与合成委托一致，尚未在原业务报告应用。

本波4 HTTP/4响应，61,802 tokens；本轮8HTTP实记148,507/新增unknown0，10m余9,851,493；全项目实记93,523,407，旧26m占额保留。runner旧行/代码during检查true。第三波尚未批准，不能因剩额度充足或12HTTP上限而自动调用。

随后 Neo 另在 WSL 以 SQLite `mode=ro`、`PRAGMA query_only=ON` 独立读取原预算库（未复制/写库）：authorization等于phase基线；原phase1032行和wave2起点1036行逐行相等；当前1040行，本轮新增8行均settled、used148507/held0；第二波新增4行均settled、used61802/held0。该检查不是仅复述runner布尔结果，也未释放历史unknown。

## 新确认问题 D-RESUME-01：恢复时把原始委托标为当前（P2）

**触发范围**：`stateful-tools-v1` 启用；Coordinator 用 `resume_content_task_id` 继续原 owner，传入合法的本次修订要求，而原 goal 含已被该修订替换的具体要求。普通初次任务、未启用 TaskContext 的路径不据此判错。

**最小实际证据**：`resume-and-sensitivity/junit.xml` 的四条 `resume_currentness_diagnostic` 属性，来自实际 native 子 Agent 输入。managed=True 的 Layout：当前 Human 完整写明本次把15mm替换为20mm；System 中却保留 `assignment.goal="Use right margin 15mm."`，并用 `Exact current application state (not a summary)` 和 `Current task/state overrides conversational recollection` 标注。actor 与 snapshot grant 没变。managed=False 两例的**实际 System 没有**这些旧 goal/current 标签；测试另行直接取得的 application_state 不能冒充已进入模型，因此不把四例都报错。

**代码机制**：`src/report_agent/content_tasks.py:109` 起恢复分支复用 DelegatedTask v1，128行的 goal 只在新建时写入；`src/report_agent/task_supervision.py:121`–122 的 assignment 返回原 payload；`src/report_agent/task_context.py:93` 把它作为 assignment，53行 current 注释与286行 System 标签把原记录呈现为精确当前状态。新的本次 description 确实由原生任务交接传入，故不是“新要求被裁掉”。

**根因与影响**：持久 owner/授权身份所需的不可变原始委托，与一次恢复 invocation 的有效指令被混为同一“当前 assignment”。保留原 goal 合理；未说明它是原始委托，并将已被明确替换的具体值仍标当前，构成输入契约的当前性缺陷。Layout15→20是直接冲突；Writer“草稿→先调查”可能仍属同一总体目标下的步骤调整，只作相邻风险，不凭其判语义执行错误。

**严重度/处置**：P2，影响当前有状态上下文的同 owner 修订恢复输入，可能使模型遵从旧具体要求或多做恢复。它阻挡“修订恢复时权威输入无冲突”的验收声明；不阻挡无关新任务和其他离线验证。四个 diagnostic 的机械断言通过不等于该冲突通过。未证模型实际照旧执行、历史报告由此出错或所有恢复均失败；不因此停止全系统。当前只保存发现，不自动实施 C1/batch1 或新增 current_goal 实体/平行状态库。

**待实施的最小方向（不是本轮已批准修复）**：保留 DelegatedTask v1、owner、原 receipt 和 reviewer/layout 的不可变授权合约；先修应用上下文的含义标注，明确 assignment.goal 是原始委托目的，当前原生任务消息可在授权范围内提出本次修订动作，不再把已替换的具体旧值整体称为当前指令。已有 delegate operation 的 request 已保存本次 description，可复用作审计，不新建任务状态库。若只澄清表示就能使真实输入没有相反的“当前要求”，不先增加另一套 current_goal。若实现确需显式 invocation 字段，必须由服务端绑定本次 delegate operation/已验证 description，并验证 checkpoint 恢复；不能让模型自行改变 owner/固定审核 scope 或以新字段扩权。应用修改前另列具体文件与 oracle；当前没有实施。

## 发现力审核与下一步

用户指出：关键在用例设计，不只是严格。现有 scripted fake 往往给定正确动作，能够证明程序传递，却不能发现 Agent 会不会采用错误策略。不同责任层必须分开测。

已交 Main 三个明确范围：

1. **新增多步组合**：上述恢复4案例已执行并审查；两条 managed=True 的真实输入当前性需修正，未扩大为模型行为失败。
2. **历史失真敏感性**：第一次仅在 bound_result 后改显示内容。实际最终边界恢复了 producer qualifiers；source 则成为合法 partial/offloaded control，inline oracle 因表示方式变化而红。这不是“两个历史错误已被杀死”，也不是 oracle 无效；是有效恢复防线和首次注入位置不适当。第二次仅在测试内存 public_value 的公开映射恢复历史裁剪/删缺项，保留归档、owner、SHA、binding 与所有恢复逻辑。`sensitivity-public-projection/junit.xml` 已独立核验：source 精确命中原 `test_agent_result_delivery.py:124` 的完整 text 断言，producer 命中174行完整 qualifiers 断言。二者敏感性成立；不是两个当前产品 bug，也未证明任意投影错误都能检测。
3. **完成复用敏感性**：只忽略 body extent 兼容差异，其他独立材料防线保留。`sensitivity-completion-reuse/junit.xml` 已核验该改变实际让新 subtree 任务错误得到 execution_complete=True，原 `test_task_supervision.py:177` 的 False 预期断言失败。敏感性成立。无需为了杀死变异再关闭其他防线。

用户另指出：“测试用例的设计也可以从trace中得到启发”。因此下一组候选以实际触发链为起点：

- 刚才实模 Layout 的根级 qualifier_placement 错误 → 原生 ToolNode 拒绝 → 下一模型可见精确原因 → fake 明确选择正确节点级参数 → 真实 DOCX。旧正确参数直导出案例看不到错误交接和恢复。必须核首次无导出/映射/正文副作用，不让程序自动改模型参数；同 operation_id 的可修正性须以首次尚未进入业务 operation 为依据。
- Writer 原生检索已 release 的经验 v1 → 临时库由 host 撤销 → 保持旧模型上下文后尝试 record_experience_use → 拒绝 NOT_ACTIVE、不新增采用记录，其他合法读不受影响。既有直接函数撤销测试不独证 stale native 上下文/错误交接。只在临时库注入宿主动作，不把 Agent 新增 release 权限。

它们是发现性测试建议，不是待实现新业务规则；具体预期必须对应现有角色/权限/发布合约。只补最小有区分力案例，不为44行补数量，也不固定生产 Agent 的动作序列。

Layout 组合最初 managed 开/关2/2通过（`layout-error-correction/junit.xml`）；随后在 `native-release-and-layout-correction` 补Mapping0显式断言并重跑两例通过：实际下一输入为 NATIVE_TOOL_VALIDATION_ERROR，含 layout.qualifier_placement 精确路径；首次业务 operation 数为0、ExportArtifact与MappingArtifact均0、原对象不变；fake 用新 tool_call ID 明确选择正确 nodes 参数、相同业务 operation ID，实际导出成功。DOCX保留原文本/condition，25/25/25/15mm及1.5行距符合独立 fixture。该结果证明程序可诊断拒绝后接受显式合法修正；不是 GLM 自主修正证据。重复两例不计新增两个唯一用例。

经验检索→宿主撤销→使用也已执行四例（revoked/active × managed开/关）：原生Writer先拿到active v1；宿主仅在临时库撤销；之后使用旧Ref的真实工具返回 EXPERIENCE_NOT_ACTIVE，application_declared记录0，当前候选搜索为空；对照未撤销两例use记录1。两类结果之后普通read_context仍成功且原内容不变。证明当前发布状态在采用时重新校验，不是旧模型上下文自动获得授权；不证明模型会自主避用撤销的策略，亦不要求旧对话历史文字消失。W11相应有限程序切面由待补升为已有证据。

## 44行程序证据对账

另26行已按 existing-first 实得 nodeid/已读断言及有效149回归证据对账，非按文件名推算。原35行加此次W11原生撤销对照，当前36行拥有其明确列出的有限程序切面代表证据；**不是36项职责全部通过**，没有接口/路径/条件覆盖百分比。

剩余8行不能升为上述切面满足：C2、W04、W07、W08、R6、L5、L6、E7。C2缺当前准则构造代表场景；W04/W08有共享存储版本/关系证据但非Writer主体；W07没有本轮实际依据/算术链；R6只有合成视觉access receipts，不独证原生vision/实际图像；L5有真实目录refresh，但完整render→页面访问未在此直接证明；L6缺基于实际页面版本选择调整的组合；E7缺dspy环境。优先复用现有有效测试，不为8个缺口加8个脚本或默许新功能。

测试敏感性红不是新增产品 bug；当前产品红也不自动意味着全系统停止。每个实际失败先定位到原始请求→工具原始结果→包装后输入→保存状态/产物，再分类并明确受阻动作。没有现有需求支撑的预期不作为发现性 oracle。

## 尚未完成

- D-RESUME-01 已有源码/实际输入证据，未修复，应用修复另明确边界。三个敏感性案例已独立审查，不是待执行或新增产品 bug。
- 剩余8行代表路径及全部职责更广条件/实际模型行为，不以36行有限程序证据冒称全部覆盖；三个敏感性及经验撤销组合已审，不再标待执行。
- E7 optional 环境缺口；真实视觉能力和完整产物检查未被这批合成 DOCX 参数测试替代。
- 真实合成后续波次尚未执行，不把当前12上限当必须花完的额度。
- 最终客户第一合同全范围 Word+issues XLSX、完整内容及视觉验收仍未由本轮证明。

## 后续对账：当前41行有限程序切面，不是41项职责验收

上述36行/剩8行是前一阶段快照，现由直接新增证据更新。Neo已读 `test_agent_duty_trace_cases.py`、`test_agent_duty_visual.py` 及既有 scoped_revision 断言，并核结果和关键JUnit属性：

- `trace-derived-native-second` 31例30pass/1fail：C2准则4种对照、W04结构6种对照、Co不适用路径→实际错误→显式有效路径、guarded schema5例、scoped revision12例及owned算术receipt例已通过。唯一红在managed Evidence的测试取错返回表示；不可计为产品缺陷，修正后结果待核。
- `native-visual-second` Reviewer/Layout各1例、2/2通过：实际临时DOCX、真实LibreOffice转换与pdfium页面、真实PNG加载，只有VisionModel响应为fake。物理页2不是打印页标签；源图/full/crop的三个SHA逐一等于实际vision收到的bytes。重复读取不增调用、crop是region_only、page999明确拒绝且不增调用。所选snapshot对象、claim对象和原PDF文件bytes三项基线保持，0 ReviewRecord，应用hash保持，socket guard未见尝试；不能声称所有子进程网络行为已被监测。

据此C2/W04/W08/R6/L5各自所列程序代表切面由待补变为已有实证；当前41行有有限代表证据，仍非接口/路径/MC/DC百分比、非整职责语义完成。剩余W07等TC03完整精确Ref/材料断言最终回执；L6仍缺实际观察→明确调整→新export/render→再次观察以及旧观察不冒充新效果；E7缺dspy环境。

首批六项Writer失败把Driver.created客户端构造误当调用；Co unmanaged无该state工具、旧review fixture缺材料、managed Evidence表示和第一版视觉result形状均属于夹具/oracle适配错误。保留原记录，不将修正这些错误计为产品修复。TC03要求加强真实packet中完整SourceArtifact Ref与实际选中块的精确断言，原“ID和excerpt出现在JSON”不足以独证版本/材料交接。已保存结果中真实payload/owner及缺pool零producer的安全判据不减少。

本批仍未修改产品。D-RESUME-01 P2当前性标注冲突未修；真实模型第三波尚未批准，10m/12HTTP是上限。已见图像不等于已完成视觉判断，成功parser/receipt不等于工程分数成立。

### 后续聚合回执：73/73，TC03加强已核

`retained-trace-final/result.json` SHA256 `ef080c3eb25a04ce96e1c371dc186087b56c0048d95d83e1ab938feccb6e6be8`：73个不同call nodeid全部通过，source before/after相等，socket guard denied_network=[]。它是新增和已有测试的并集复跑，不是73个全新发现案例或全系统覆盖。Neo核TC03两配置关键JUnit属性及已读的精确packet断言：完整source_version_binding.object.ref、selection、source_id、ordinal、定位和全部选中原文均匹配；返回和保存的source_refs/locator/excerpt原样，缺合法引用池时producer0。W07此有限切面已证，当前42行有明确程序代表证据；term值的工程来源、公式和分档适用性仍未证明。

E7真实缺dspy负路径保存failed、无student/holdout执行和candidate、同目录拒绝重复执行；不是host授权强制测试或正向GEPA执行。保留E7正向environment-blocked，不为了44齐把负路径当完整正链。L6调整后新版观察组合仍待实际结果。D-RESUME-01仍未修；本轮产品源码无改动。

## 本阶段审结：43行有限程序切面；E7正向blocked

`native-layout-adjustment/result.json` SHA256 `7a4e85fdaea385d87357c37ad0d263d61791d5f1843cdb75c6bf56ec10ea48e3`，1/1通过。Neo已读新增源断言及JUnit属性：原生Layout读取旧render，fake明确选择右边距15→20mm、Normal12→20pt，真实DOCX的两项参数变化、段落文字不变；新render绑定新export及其digest，实际vision收到的新旧PNG SHA各自匹配且不同。旧render仍能合法cache读取，明确带旧export/render Ref，没有重标成新版。所选snapshot/claim对象及旧DOCX bytes保持，0 ReviewRecord，应用hash保持。这里没有模型自主选择调整、判断改善或整报告视觉验收的证据。

当前43/44行具有各自明确列出的**有限程序代表切面**；不是43项职责完整通过，亦不是接口/路径/独立条件覆盖率。E7已证缺依赖负路径但正向GEPA仍environment-blocked，不安装依赖凑齐数字。全部职责的更广边界/组合条件与专业判断仍按coverage.json逐项保留。聚合73与此次1不是74个全新用例，也不把跨运行重复节点重复计数。

### 本轮真实调用成本纠正

第一波Co45,531（37,339输入+8,192输出）及checker11,868（3,676输入+8,192输出）合计57,399 tokens；测试runner沿用了8192输出上限，且公开usage显示该输出额度全部用于reasoning，未产生公开动作/审核判定。当前实际系统配置65536；这不是用户10m验证预算不足，也不是远端unknown。归类为**测试额度设计受限、对本次职责结果无产出的测量成本**。上限选择错误有直接证据，不能推成全57,399可无损净省；更高额度的同场景仍需真实调用才能取得结果。不得把它们包装成完整验证收益。

第一波Layout26,904有真实参数层级错误的发现价值，校验器正确拒绝；Optimizer2,402只取得合法动作，未执行。第二波61,802为明确关联容量受限样本的有界复测与两个新文字契约，取得简单冲突not_satisfied/原表复制/限定词修订等有限结果，Co选用路径不适用且未执行。当前本轮8HTTP实记148,507、0新增unknown，原26m holds保留；10m与12HTTP都是上限，不是花完要求。第三波不因凑44自动启动。

### 下一步优先级

1. D-RESUME-01是当前唯一已确认、未修的本阶段程序P2：managed恢复的旧goal被标为当前权威。先解释最小修复边界和真实输入反例，保留原任务/owner/receipt；将当前诊断转为能杀死旧错误的回归，再实施。它阻挡“恢复指令当前性明确”声明，不阻断其他无关测试。此审结本身不批准产品热修改。
2. 继续以trace中的部分完成、条件未知、缺料与错误恢复的多步分歧为发现用例；优先沿现有参数化native骨架，不用更多幸福路径或单次schema通过替代职责效果。涉及真实模型前先说明它将解决哪个尚缺判断；无需机械补第三波。
3. E7正向评估环境缺口可后置，不为本轮报告主链安装可选引擎。客户首合同完整Word+issues XLSX的实际内容/视觉验收仍另有边界，本轮不是恢复旧报告或验收通过。

本阶段仅测试/诊断/审查文档，未改应用；Neo只审查未运行测试或付费。全部通过计数、模型样本和已知问题分开记录；发现失败先审root cause，不降低oracle换绿。

## 探针默认输出容量：2026-10-19预审决定（尚未验证修复）

用户追问hardcode后，Neo只读核当前 `scripts/probe_agent_io.py:170/305` 仍各默认8192；179取 `requested_output_limit or model.max_tokens`，219 Agent与239独立文字工具均以该值覆盖实际调用。第二波显式0只绕过默认，没有修复重复默认。确认这是本轮测试harness的P2测量有效性缺陷；阻挡“默认probe复现正常模型容量”声明及沿该默认继续真实调用，不推断生产所有模型常量都是同类bug。

同意Main在说明边界后，仅改测试脚本/测试：函数和CLI默认0，复用现有0=继承configured_model语义；正值显式override只为容量边界实验。记录configured/requested/effective及来源；缺少或非法实际配置明确0HTTP拒绝，不引入新的fallback常量。生产 `deep_models.py:337/357` 的模型/服务/推理配置容量是另一层策略，本批不改、不凭此次事件判全部错误。没有新配置平台、产品源码或付费验证。

最小验证为Writer Agent和独立text-normal两条真实probe→实际adapter→MockTransport，各比较默认继承/显式override的最终HTTP JSON max_tokens，确认原模型配置未被改写；非法输入或缺配置上限为0HTTP拒绝。保留真实角色完整schema、正常工具packet/parser，不用toy JSON请求替代。该决定是最小修复边界认可，不是修复已实施/测试已通过；旧57399测量成本和原始失败不重写。

## 2026-10-19：矩阵remaining_gap旧文字校正

逐行对照已有F/R及已审结果，修正13行remaining_gap，不新增测试、不升级整项完成：C1/C4/W05/W08/R3/R4/R6/R9/L1/L2/L3/E3/E5。重点消除三处事实矛盾：R4已实模取得简单冲突checker判定并保存临时记录；L1/L3已实模取得Layout下一动作（边距/行距正确但参数层级非法）；W05已实模测简单双列表和限定词修订，不能继续写“表格/局部修订待测”。

父子显式partial交接、R3 linked receipt反例、E5候选保存已有证据，不再标骨架未审；R6的新版观察组合仅在Layout已证，Reviewer同类重检仍待证。各行仍保留模型自主组织、复杂资料/表样/图注、专业判断或全报告效果等真实缺口。43有限切面/E7正向blocked/D-RESUME未修的状态不变。历史阶段叙述保留，但以最新矩阵和日期为当前指针。

### H-OUTPUT-DEFAULT-01修复审结：仅测试工具、offline证据通过

对比归档 `output-limit-before/probe_agent_io.py` 与当前脚本，修改仅两处默认0、非法override提前拒绝、无有效配置时关闭client、configured/requested/source/effective审计字段与CLI说明；未修改src/model factory、原full schema、packet/parser、预算准入或原付费结果。

`output-limit-final/result.json` SHA256 `ebde766bea2022de9a2fcdc8aef3203f0284fb17d49ab95210f6ea61a5c16da1`，9个新容量测试+5个既有预算测试14/14通过，source before/after相等，denied_network=[]。Neo已读新增测试的oracle和4份持久归档wire：默认Writer/text-normal均configured65536、requested0、实际max_completion_tokens65536；显式override4096两例实际4096，原模型配置仍65536。两个Writer请求的全部42个tools与native tools完全相等；两个独立工具的原system/user文本与最终wire完全相等，实际parser返回completed且fixture原文不变。CLI仅parse即验证默认0未启动波次；负override/缺配置两入口4例均0HTTP。

首轮5fail中3个容量/CLI默认是目标反例，另2个显式覆盖缺审计字段同属本补充契约，不能数5个独立产品bug；第一次after两个失败把原始工具候选当BusinessBoundary信封，是fixture误读，保存旧记录后按真实state=completed/payload修正，没有减弱容量wire oracle。

Neo将H-OUTPUT-DEFAULT-01处置为**已修、offline最终wire已验证**，关闭“默认容量不代表配置”的该项阻挡。证据限当前Writer/独立text-normal和GLM兼容适配器；不冒称所有角色、官方DeepSeek131072、其他provider均已实测，不增加新的真实调用。43有限程序切面/E7正向blocked/D-RESUME-01未修状态不变；旧57399测量成本保留。

## D-RESUME-01修复设计启动前判断（2026-10-19）

已核content_tasks/task_supervision/task_context/deep_runtime/decision_state及WorkingSummary实际路径。确认原assignment@1保存goal且当前description通过原生消息另行送达；operation只保留digest/response。最初“改标签即可”方案不足以保证summary压缩后新委托仍可恢复，已在实施前修正为既有任务ContextVar绑定本次invocation，并由exact/compact/summary同一投影传递；真实handler每次调用含自动followup都需绑定自己的description。具体四模块边界和fake/恢复/反权限oracle见neo-plan最新节。

这是设计准许进入说明/实施，不是修复通过；D-RESUME仍open。禁止改assignment历史/owner/grants/review范围、引入新状态库或C1实现；下一真实合成波待具体fake/wire证据审过，不能用此前第三波pending当无限暂停，也不能自动凑满剩4HTTP。

## 最新用户顺序：先用例设计，D-RESUME修复及实模第三波暂停

截至本节仅只读设计审查：neo-plan新增TD-R01/TD-J02/TD-G03/TD-T04，分别针对摘要后当前委托、公共内容判断、缺完整指南表样、三child目录真实组合。它们是待审核/未运行设计，不把候选current_invocation字段规定成oracle，不先修后造绿例。

“工具内容判断进入返回结构”目前分层事实：

1. 独立checker已有typed Assessment/ToolObservation，真实简单冲突not_satisfied和临时ReviewRecord样例；native inline/offload→下一Reviewer的reason/verdict/state/coverage/check_results完整传输已有fake实得。observations.limitations/findings的独立逐字段长尾检查尚缺。
2. Writer qualifiers/claim_kind/body及generation_notes结构存在；test_agent_result_delivery.py:160–189实际下一输入和原样保存已核。可选字段/任意qualifiers字典不自动保证每次内容判断足够，完整receipt也不证明语义。
3. 通用analysis在evidence_analysis.py:246是公开analysis字符串，prompt:39要求支持/反驳/未决/证据范围；三角色两工具的全文传输已有siblings证据。这种返回并非自动缺陷，缺的是按任务检验判断内容是否充分、是否正确及Agent实际如何采用。Learner findings字符串同理已有完整payload/尾部样例。
4. “实际下一wire可见”已有上述有限路径；fake消费路径/真实单步动作、独立工具语义和最终报告效果仍是不同证据。不能声称44职责语义全覆盖，也不能说这条链从未测。

Main新增设计文档待Neo审核；本节不批准测试执行/修复/新付费，也不撤销已有离线结果。用户持续目标保留，工作顺序按本次先设计校准。

## 对实际9组测试设计稿的独立审核（2026-10-19）

已读 `test-design-before-repair-20261019.json` 全部9组和对应HTML，核9个ID/标题展示一致；稿件SHA分别为 `56adeee61f55ca84867dbf0d5a338a6250fc06c55850fb21a8b614461279177b` / `34d6d1eb31235404e0c9c13141a54ccb5aa917e037ddf4d28d8a15ab74917aad`。仅核设计与最小相关源码/已有trace，不新增测试、模型调用或修复。

判定：**总体方向可采用；以下五处澄清后才作为可实施测试规格，不是测试已通过或44职责验收。**

1. A01真实工具参数：`export_content_snapshot(operation_id,snapshot_ref,layout={toc:true,refresh_toc:true})`，随后`render_content_export`。toc/refresh_toc不是顶层参数；不凭工具名字存在当参数正确。单目录可以多页，当前稿正确保留此区别。
2. R02允许精确授权引用恢复，但必须当前输入给出实际本次调用的明确引用、当前角色已注册可用的读取路径，并真正恢复全文/末尾条件、核身份；库里存在、猜event日志、读回首次目标都不满足。其他task不得自动串入当前委托/权限；不能禁止当前本就合法的历史DelegatedTask读取。R01可保留旧goal，不把它存在本身当错；删note也不能使R02自动通过。
3. J02所列perform_assigned_review是内容审核，不能据此覆盖R7 artifact路由；后者perform_assigned_artifact_review列兄弟待测。Fake程序层可断言partial/remaining原样到父输入、程序未把execution_complete改true；父模型如何总结/决策由J04检验，不把fake脚本当自主消费成功。
4. J03/I01敏感性保留原始选材/模型公开结果，在随后的程序包装/投影/传输点注入失真并由原消费者oracle抓住。主动少选资料或修改fake响应本身是不同试验，不能归为程序裁剪。
5. A02“规定字体字号”应给明确fixture数值与来源；核实际有效属性，包括直接覆盖及合法例外，不只核style名。

J01/J02按工具现有契约分别测试公共判断及限制，未强制所有工具统一verdict；J03明确analysis字符串不是自动bug；J04允许继续读取/补证/条件结论等多种合法行动，且只设计未派发，这些判断合理。缺表样输入应检验未选与被程序删选中材料的区别，不能以JSON合法等同表样任务完成。

本审查没有更改Main稿；由Main修订后重新确认五点，不能将本节视作无条件执行批准。候选D-RESUME接口仍暂停，当前修复前测试必须先固定行为oracle。

### 实际修订稿复核：设计审查通过，未执行

已复核Main修订的JSON/HTML改处及格式标准归档原文；JSON SHA `ce266a6ca4b5b9cfea2d7ec7803244bd8f1359372d60fec8be469999fed1a8a5`，HTML SHA `50e394d161ecfef4ad162ddb3da5ac0c52f041d71dfd4059b2ace18f6facef6f`，9组ID/标题展示一致。五项要求均解决：真实layout参数层级；R02确切当前引用/已注册读取/真实恢复且不扩大历史读取禁令；J02内容与artifact范围、F状态与实模总结分开；J03/I01仅在原始材料/输出后的程序传输层注入；A02来自外部标准的明确字体字号及有效格式/合法例外。

格式原文SHA `2b50a74db2bb3aa9566de5373d7765cb6b512f7771031b3f8667dd7673fe2443`已独立核，2.2/3.1/3.3/4.1/7.2/10.1支持该有限fixture；小二/小三/四号18/15/14pt、小四12pt、五号10.5pt、三号16pt为测试中的明确换算。封面单倍等条款保留，不以正文通则覆盖。A02未包含标准全部编号/页眉页脚等要求，不外推成完整客户标准验收。

Neo判定：这九组方案可作为**已审核的用例设计**，无剩余阻挡本稿采用的问题；不是九组已运行、不是修复批准、也不是44项职责全覆盖。R02若当前实现已满足必须如实绿；复现应在目标行为断言失败，不能人为破坏前置条件造红。J04允许多种合理行动，真实语义样例仅为后续计划，当前0付费。D-RESUME实现/第三波仍按用户先设计顺序暂停，待下一明确执行范围。

## 用户授权9组fake用例实施：审查口径（2026-10-19）

设计审查之后，用户现授权Main落实保留测试，先fake复现、不修应用、暂不派真实模型。当前九组的最低有效观察面已录coverage.json.nine_group_fake_stage_20261019；不是测试结果。Main可分工A01/A02 test-only真实Office产物，Neo只审核设计/源码/实际trace。

优先R01/R02目标复现，再J01/J02/J03/I01真实I/O组合；J04 fake阶段仅证明程序消费接口/分歧对照可执行，不证明模型自主采用正确。A01单TOC/实际refresh/render，A02独立标准有效格式均需真实产物，不能手改输出或让渲染fake算实际图。

复现有效性必须先证：summary真的触发且原指令不在普通窗口；缺表样fixture没有被另一个SourceArtifact whole-body input自动补全；合法Assessment先能到达被测包装边界，不能让parser/权限错误冒充判断丢失。不同managed配置权限工具可能不同，不能强给工具凑兄弟覆盖。初始诊断红/受控故障注入杀死/夹具错三个结果分开，代码不修、oracle不放宽。

下一收到Main测试代码/回执后再逐组定通过、实际产品问题、环境/fixture问题和未覆盖子路径。旧43有限切面与E7 blocked是既有快照，不因开始新9组就清零或宣称已完成。

## 9组实施首批结果审核：R01/R02精确目标红，产物测试需补两处oracle

`resume-first/result.json` SHA `f9737c311f31003614c160a84bf2bbaf9f076bb75cd671f28d597b7c55ee6dcf`，归档测试hash与当次回执一致；13例4fail/9pass，src before/after相等、denied_network=[]。Neo逐条读JUnit captures/真实序列化wire：R01仅changed+managed的Writer/Layout命中既有旧goal权威冲突；新Human完整到达，其他same/unmanaged对照通过。R02 summary输入确收到本次完整指令，真实归并后下一wire及注册read_decision_state([])恢复均无该指令/尾部；原始目标控制能恢复，原生runtime last_error=None，未被其他错误提前阻断。

判定：4红是D-RESUME-01一个共享当前性问题的两角色/两切面复现，不是4个独立产品bug。摘要后“本次指令可恢复”缺口扩展该P2证据；不是原文从全部存储永久消失，也没证明模型真的执行旧目标。范围限当前输入+已测试全state恢复lane；明确引用/checkpoint/followup另列，取消真控制待后续回执。当前测试Human移窗应由原始Human身份或flattened完整内容判断，不能仅content==string。应用仍未修。

A01/A02 `artifacts/run1` 8/8实得：原0/1/3child toc=True均1字段/1Office索引，toc=False为0，历史条件memory mutation为4字段/4索引且被原单目录oracle杀死；A02 global/local正确属性0violations，旧参数对照12violations，标准源SHA吻合。Neo直接核44份持久资产SHA，并打开保留DOCX的XML核root/三child实际存在及单TOC。宋体实际fontconfig为DejaVu Sans，保持视觉字体未验。

保留测试还需小幅补强：A01 fixture预期文字目前未列root body；A02有效字体检查没有逐cell断言导出表格实际文字与独立原表全等（存储节点未变不等于输出原文没变）。这两项是test oracle缺口，不是已证产物错；已请Main/worker仅test补断言并保留run1。不扩大所有格式条款/真实模型。

J01另有新缓存候选：同输入成功后新外operation_id可命中同raw cache，最终receipt_digest相同，text_work.py末尾无条件INSERT同receipt key。源码机制支持，但待最终实际异常、调用次数及两个父状态审查后定案；不立即改应用、不把候选算已修。
