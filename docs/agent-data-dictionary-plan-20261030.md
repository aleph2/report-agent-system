# 全Agent业务数据字典方案——待实施设计

## 1. 本次交付、适用范围与已有证据

用户决定：方案覆盖所有现有Agent，明确LLM返回、程序补齐、保留校验；先交Neo审核，落地先Co/Reviewer；本次不改代码、提示词或配置，不发送模型请求，不启动真实报告。本文中的字段与内部表示是候选设计，不是已经可调用的接口。

当前分层主链代码：Co协调，writer/reviewer/layout由deep_runtime.py构建子Agent；learning_runtime.py另外构建experience_optimizer。Knowledge与rubric_grader属于旧入口/显式兼容路径，不因本方案新增角色或启用旧入口。OCR/视觉、文本处理、计算、导出是工具能力，不自动升格为Agent。本文覆盖这些工具的通信原则，不改变其算法或增加强制调用阶段。

已有局部证据：Co字典补全实验仅字典改变，原schema/system/tool说明/业务材料/原binder一致，19项离线通过，同用例新任务1调用0拒、6,606 token；旧CoB为3调用2拒、21,065 token。Reviewer局部实验1调用0拒，但保存的是实验model_assessment记录，**没有证明正式ReviewRecord与下游消费者已兼容**。两者都是非盲有限样本，不是全部角色或端到端生产验收。

## 2. 统一的是通信边界，各业务使用自己的字段

1. 程序按当前操作、已鉴权任务、真实材料与已存状态组装字典。每个key有业务含义、值类型、required/optional/conditional/program-bound、合法值/可选scope、遗漏/null/空值语义。不把全部数据库列作为可选字段暴露。
2. 一个字段定义同时产生工具schema、简明字典及字段错误说明，避免手工维护两份冲突合同。当前权限候选由可信对象与任务授权计算，不能从文件名或模型文字生成权限。
3. scope是任务内短引用，目录给业务名称和类型。引用字段明确填ref而非label/UUID/整条对象，并逐字段列合法候选。程序持有精确对象、版本和归属；固定上下文不要求回填，多候选或尚未决定的选择仍由模型表达。
4. LLM返回业务选择、正文、判断、进度、问题和原因。程序绑定身份/版本/关联/存储对象，不新增格式判断LLM，也不从长文猜通过、严重度、完成范围、引用或授权。
5. 外层消息以语义清楚的key-value表达，不加Agent名前缀；工具/操作名区分命名空间。表格行列、章节次序等**业务本身需要的结构**允许保留，不序列化成难读字符串来冒充扁平。
6. 查询没有修改也有必要返回信息；创建没有既有主键，由程序分配新身份。更新只返回目标scope和本次修改字段：省略保留原值，显式null/[]仅在字典明确允许清空时生效；false/0不当作省略。创建的缺省仅用声明默认，不能继承别案判断。
7. scope映射、字段合同版本和基准版本随现有任务/请求记录保存，恢复时还原同一绑定，不因列表重排或latest改变引用含义。映射丢失/过期须明确报错，不盲猜。
8. 原始模型消息、实际工具回执与解析后的内部引用保留审计。模型可见成功/错误返回用简洁业务字段和可续用scope，内部身份不反复回灌；副作用未知时查询原操作回执，不能谎报未保存或生成新ID重放。

## 3. 全角色输入、返回与程序职责

### 3.1 共用操作

|操作族|LLM返回/选择|程序补齐|必须保留|
|---|---|---|---|
|读取/检索|target_scope、query、需要的字段/正文范围、页码、续页位置，按操作适用|精确资源版本、权限、实际内容/读取回执、分页标志与合法后续scope|不把索引/摘要当完整正文；不把未返页当已读，不因检索命中授予权限|
|修改已拥有内容|target_scope＋明确修改的业务字段|原记录其他值、基准版本、作者/任务身份、按该动作已验证的事务边界保存及新版本|所有权、CAS、仅允许字段、显式清空、引用有效性；不覆盖别人内容；跨数据库/文件不承诺天然原子，失败/unknown如实保留|
|交接/反馈|目标、问题、实际证据选择、影响；下一动作等适用时可选|已绑定目标版本、操作身份、反馈记录关联|保留未决事项；不强加必填接收者/固定后续阶段；文本不授予权限|
|复用/更正|原结果scope、新目标/版本选择、适用理由及实际修改范围|历史关联、新旧版本、合法supersede/reuse记录|不因同名/内容相近自动沿用旧通过，不删除旧记录或失败回执|
|经验查询/使用|query或experience_scope、应用目标、采用理由|库边界、精确经验版本、有效/撤销状态、使用记录|不取latest代替绑定版本；引用经验不证明本次判断正确|

### 3.2 Coordinator

|动作|LLM应提供|程序补齐|
|---|---|---|
|委派审核|criterion_scopes、artifact_scopes、review_question、instructions；目标/完整依据未固定时另显式选择相应scope|actor/project/task、子任务ID、精确snapshot/criterion/artifact refs、完整已固定委托依据、MappedItem等内部结构|
|定义/修订标准|目标要求、审核范围、预期结果、证据要求、允许局限；实际依据选择|Criterion ID/版本、已绑定Requirement/Source关联、原记录未改字段|
|选择交付/执行决定|实际snapshot/Word/Excel选择、continue/wait/handoff/terminate、理由、未决事项及其处置|已存成果版本、实际审核适用性/未决状态、选择和执行记录|

Co仍决定做什么及委派范围，程序不预选C7、不默认全选、不把此次子集替代完整标准依据。完整依据只有在当前任务已明确固定时可省略。内容目标与导出/渲染成果分开；子任务只获当前父任务允许的材料与操作。任何必需材料必须通过已有授权绑定，不靠instructions提及文件名取得访问。

首步适配仅覆盖已验证的委派类型；标准CRUD、交付决定等先列字典，未实施的旧业务操作继续使用完整旧合同，不假称已完成全部Co迁移。

### 3.3 Reviewer

|字段|返回要求|含义/程序边界|
|---|---|---|
|review_scope|业务单元未固定时必填，已明确固定可省略|选择当前分配单元；程序恢复criterion/target/scope_id/assessment_kind与成果版本|
|execution_state|必填|模型报告not_started/partial/completed/blocked，程序不能从读取回执推断完成|
|verdict|必填，可为null|satisfied/not_satisfied/undetermined或尚无判断；程序不从文字提取|
|assessment|必填|模型原始判断、比较依据、发现和限制；仅在同一个单check语义完全一致时复用于reason及check.result|
|evidence_scopes|有实质判断/完成检查时条件必填|模型实际采用的已读证据；程序展开真实回执及版本，不能自动把可用材料全选|
|remaining_work|未开始/部分/阻塞时条件必填|说明未做工作和原因；完成时省略/空值须符合字典|

正式字段名统一建议用evidence_scopes；实验evidence_indexes到此命名的变化也须纳入后续schema/wire审查，不宣称原实验已测该新名称。

**负面发现不能丢失：**verdict、assessment及未完成事项进入正式记录和现有状态/交付读取。需要结构化Finding时仍由模型明确finding_type、description、locator_state、impact、needed_outcome、basis_kind等实际业务值，程序只绑定当前check和证据关联，不从assessment自动抽取/猜严重度。它们是条件适用的业务字段，不强迫正常结果重复填写。可用平面消息组装原Finding，但具体多finding/跨check关系首步不迁移，原通道保留。findings为空只表示未提交结构化条目，不能作为“没有问题”的机器证明。

首个正式适配范围：一个明确业务判断单元、一个required_check，先复现C7导出一致性；not_started/partial/blocked/undetermined/not_satisfied均须可真实保存，不能只支持成功。复杂多check、多目标、逐页render等仍保持其原有能力；未表达的关系不能偷偷补齐或降级。

### 3.4 Writer

|动作|LLM应提供|程序补齐|
|---|---|---|
|新正文/修订|正文text、标题/内容种类、事实/推断/建议属性、必要限定；更新只返回变化字段|新ID或已选目标的精确基准、owner、版本、保存回执|
|编排/来源关联|parent_scope、次序/包含关系、实际采用source_scopes与关系业务含义|ContentNode/Relation/Evidence等存储关联及已知版本|
|表格/图/工作簿内容|实际列、行、单元格值、图源/图注、工作表选择与顺序|对象和文件身份、单元格/表/报告关联、导出实际结果|

不能让程序猜章节结构、风险等级、正文、引用来源或是否改写；表格可保留必要数组。事实来源、结构循环/次序、所有权、版本、工作表合法性及与报告关联的检查继续执行。第一次不把save_text_node、commit_objects等全部替换；先给每类业务操作明确映射，后续单独实施验证，禁止直接按模型key拼接SQL或任意写数据库列。

### 3.5 Layout

|动作|LLM应提供|程序补齐|
|---|---|---|
|版式调整|导出/快照scope、实际希望改变的版式业务字段，如页边距/缩进/字号/表头重复等当前能力支持值|原配置未改部分、精确内容版本、能力到LayoutOptions的映射、新导出/渲染ID|
|页眉/页脚来源选择|已采用内容行的scope及必要选择|原正文版本与定位关联；不允许借排版创造工程正文|
|视觉检查/能力缺口|实际页scope、观察、问题位置、影响、能力请求理由|真实render/page回执、导出归属及请求记录|

字段及合法范围必须从实际能力目录生成；上述是业务示例，未承诺当前接口已有这些同名参数。保持数值边界、合法样式、内容只读、Word/Excel能力边界和实际渲染校验。新排版文件不能继承旧文件的审核通过；工具导出/渲染完成也不是模型视觉验收。

### 3.6 学习Agent experience_optimizer

|动作|LLM应提供|程序补齐|
|---|---|---|
|反馈处置|feedback_scopes、candidate/no_change/insufficient_evidence、rationale|当前实际分配反馈、claim/job/actor身份、原子保存|
|经验候选/修订|kind、title、strategy、conditions、verification；更新时experience_scope及变化字段，实际依据选择|库/project/customer范围、反馈关联、候选ID/版本、expected_version与状态|
|采用/评估建议|精确候选选择、理由/验证建议|host已有评估数据与度量绑定、实际试验回执及发布状态|

学习Agent只能提出候选，不能因数据字典获得publish/修改评估器的权限。反馈归属、跨客户隔离、失效/撤销、并发版本、候选与反馈关联等保持。学习机制和优化算法本次只列通信边界，不改源文件、策略或自动发布；学习模块仍受原共享checkout所有权约束。

## 4. 程序统一补齐清单及明确不可补齐的信息

**可以补齐：**运行时actor/project/task、原生tool_call对应operation身份、当前已固定对象和精确版本、所选scope到内部Ref映射、创建ID/时间、原记录未修改值、已明确的同任务准则/成果/依赖关系、真实工具产生的回执及新文件ID。

**只在明确条件下补齐：**仅有一个候选不等于已被选择；只有上下文已经明确固定才省略。dependency_refs只有已固定或模型选择才可绑定；required_check索引只有单元唯一时机械恢复；覆盖只来自模型明确状态，不能由可用材料/读取成功推断。

**不能补齐：**新事实、正文、关系的业务含义、选择了哪些依据、实际完成范围、verdict、问题类型/严重度/影响、未决项或工程批准。数据库关联可以自动组装，业务判断始终保留来源。

## 5. Co/Reviewer首步的最小程序接入候选

这部分是后续开发触点，不是本轮改动清单或已经获准修改的文件。

### 5.1 共用字典与Co接线

- 用一份小的业务字段定义生成schema/人可读字典/字段错误信息，并在当前可信任务中绑定scope目录；复用现有任务状态与操作回执，不建通用消息总线、全局URI体系或新账本。
- 在现有Co工具组装/实际调用边界接一个适配：平面选择→现有ReviewSelection→delegated_task/review_binding。真实工具名字/调用身份需贯通，不能只变展示schema而native executor不认，也不能手工建DelegatedTask绕开权限。
- Co其他task角色委派、Writer/Layout、旧run默认行为保持。一个运行只暴露当前适用且一致的工具合同，不混合旧nested模板和新平面schema。
- 新工具若改名，必须沿用operation_identity/native_operation_tools的actor+tool_call幂等和原回执查询；不是让LLM填写operation_id或把两个工具调用静默当同一个。

### 5.2 Reviewer正式记录：需要的小扩展不能隐瞒

实验侧车不进入生产。首选待审内部表示是给CheckResult增加可选assessment_evidence，表达来源为model_assessment及该check选中的多个真实receipt；模型原文保存在现有result，同一单元reason可引用相同原文。**不复制成每个receipt的Observation，不伪造读取事实，不增加第二个审核记录体系。**旧Observation、旧ReviewRecord、旧数据原样保留。

当前CheckResult.supported_account要求completed有observation_indexes；ReviewItem.consistent要求非空verdict有observations。这两条结构条件需要明确支持“旧观察链接”或“新模型判断证据组”两种合法表示；其业务要求仍是实际引用了合法、成功、足够范围的证据。不能称所有validator原样未动，不能只加字段并跳过旧校验。首步不混用两种表示来扩大范围或隐藏未完成检查。

用一个小的证据解析入口把当前check的合法支持材料展开给原校验/消费者，逐点核：

|现有位置|必须复用/适配的责任|
|---|---|
|content_tasks / hierarchical_tools / deep_runtime / task_context|实际schema、字典注入、原生工具执行、可信身份和任务上下文一致；内部新字段不能意外暴露于LLM或旧schema|
|content_models / content_store.submit_review|内部兼容表示、actor/task/所有权、快照版本、receipt实际归属与失败读取、单事务写与操作幂等|
|review_input / artifact_review|check→证据关联、正文范围/结构元数据边界、必需材料、精确成果/页及真实成功读取；不能把泛有receipt当全范围证据|
|task_supervision / review_coverage|全部分配check状态、未决项、范围对账与正文/成果覆盖；不把一项完成扩成全任务|
|review_status / content_delivery / 复用历史读取|显示原判断及所有关联回执，not_satisfied/undetermined和原文问题不丢失，历史/当前版本适用性不变|

这是受影响责任清单，不能在实施前承诺每个文件都要改；先以调用链与测试确定最小必要补丁。实际源码目前多处直接读取observations[].receipt_id，必须逐项检查，不能只让新保存函数接受输入就声称正式兼容。

### 5.3 保留的校验

1. 字段类型、必填/条件、enum、未知key、scope类型/存在/当前任务映射；不把错误label自动猜成另一个ref。
2. actor/角色/项目/子任务绑定、所有权、父级授权、任务固定范围；短scope不是权限令牌。
3. 精确snapshot/criterion/源/成果版本、CAS、同版Word/Excel/Render关联；旧通过不自动批准新版本。
4. 实际receipt由当前合法执行者产生、发生在判断保存的有效时序内；失败读取/索引结构不能冒充正文/视觉观察。
5. 每check的已引证材料/正文extent/必需页覆盖；完成与通过分别验证，partial/blocked不能假通过，已成立负面不能被后续阻塞抹去。
6. 显式结构化confirmed_defect与satisfied冲突、input_gap不冒充confirmed内容缺陷、Finding/检查证据合法关联。仅有自然文不能保证程序发现语义矛盾，缺必要分类时保留为未解析/未决，不能宣称已识别全部问题。
7. coverage只覆盖实际snapshot成员，成果不乱塞入正文目标/对象对账；一个检查的完成不代替整个委托。
8. 同operation幂等、未知副作用回执查询、原子记录、失败记录/历史保留；不释放或重放预算unknown，不新增计量系统。

## 6. 提示词冻结与正式启用前的真实输入审查

本轮不改任何职责提示、工具说明、schema、上下文组装代码或配置；本文件只描述候选。

已证耦合：content-coordinator-v4.md含review.deliverable/standards/scope；content-reviewer-v4.md含coverage.checked/check_results/observation_indexes；native-submit-review-selectors.md含旧items及回执填写要求。正式新接口若仍与这些旧要求并置，会重现合同冲突。**程序补齐存储对Agent透明，不等于现有输入文本完全无需处理。**

后续正式启用前，须先提交system、工具说明/schema、当前任务字典、错误/成功返回、委派上下文的实际差异供审核；纯格式耦合的必要调整与职责行为变化分开列。当前不重写这些文字，不用实验职责投影偷偷替换生产默认，不把“程序动态组装”当作绕过审核的理由。

## 7. 后续落地顺序及验证

1. 先冻结Co/Reviewer小范围字段合同、scope绑定与正式证据表示，明确负面/未完成处理；其他角色只留方案，不提前重写其工具。
2. 若用户后续授权实施，先离线验证补齐/新旧记录/权限/版本/空值/未完成/多receipt/单份成果缺失/失败读/幂等与消费者读出；Mock验证实际入口，不以旁路函数替代。
3. 审核实际LLM输入差异，解决提示词冻结涉及的必要格式耦合后，才在新隔离任务验证Co与Reviewer；分别记录首次接受、全部拒绝、事实质量、input/output/cache token、模型和端到端时间、used/held。验收必须读取真正的ReviewRecord及交付/状态结果，不只看exit0。
4. 两者正式链通过后，再按同一原则分别推进Writer、Layout及学习通信；保留原所有权与发布权限，不同时改职责定义、学习机制、模型或业务算法。

方案审核不等于代码已接入、提示词获准修改或效果验收。第一阶段小范围未覆盖的旧能力保持可用；回退由明确合同/当前任务选择，不能在失败后悄悄换存储路径或放宽规则。

## 8. 证据与本次技能/范围记录

源码事实：hierarchical_tools.py的content_tools及submit_review；deep_runtime.py的roles/subagents与BusinessBoundary；content_tasks.py的task_tool/delegated_task/native_review_submission_schema；review_scope_selectors.py；content_models.py的Observation/CheckResult/ReviewItem；content_store.py的submit_review；review_input.py、artifact_review.py、review_status.py、review_coverage.py、task_supervision.py；learning_runtime.py的build_optimizer/optimizer_tools。图谱检查无覆盖此源码的graphify-out/graph.json，复用先前覆盖缺口并核具体源文件，未重建图谱。

历史实验：../co-dictionary-scope-fix-20261030/results.md、request-dictionary-diff.json；../human-readable-contract-trial-20261030/results.md；../flat-message-contract-20261030/user-clarifications.md。本次不用未验证记忆代替当前源码。

Main使用using-agent-skills划定设计/审核阶段，接口设计技能检查wire与存储边界，agent-prompt-design仅检查现有输入耦合，不改角色，Ponytail约束最小范围；Langfuse实验方法只复用已有局部证据，不新增平台接入或LLM咨询。本次验证限文档、来源与源码未改核对，不为文档运行产品测试。

## 9. Neo审核结论与Main处置

Neo（rollback_review）只读核当前入口、字典边界、角色/工具区分、来源权限、证据双路径、消费者及提示词冻结后，同意本稿作为待实施设计交付，无阻断本次文档讨论的发现。Main已采纳将“原子写”限定为具体操作已验证事务边界的建议。

以下仍阻断正式接入或宣称兼容，不代表方案已实现：新旧check证据表示与全部原校验等效；负面判断/未完成事项在status/delivery/history消费者不丢；内部字段不泄漏到实际SDK schema且伪造被拒；新接口与有效system/tool/context/error合同一致。解决这些问题的动作应落在后续已审核小补丁与相关测试内，不以此新增运行时审批循环、额外模型或架构平台。

审核记录见review.md；产品源码保留验证见source-check.json。
