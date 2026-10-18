# 系统设计、用户需求与智能体设计汇总

整理日期：2026-10-17。对象：独立项目 report-agent-system。编写：Codex；需求和判断边界核对：Neo；运行时与 prompt 路径核对：body_alignment_review。

本文件回答三个问题：系统现在按什么设计运行；用户究竟要求什么；每个智能体负责什么、实际收到哪些提示。它同时保留设计目标与实际实现之间的差距，不把设计文档、测试通过、模型自述或任务结束当作最终交付验收。

**当前结论：系统已经具备资料读取、版本化内容构建、独立文字处理、Word／Excel导出和审核能力；但本次第一合同段全范围报告尚未完成符合客户要求的完整验收。最新布局及材料交接调查发现了真实缺口。当前处于暂停实施与付费运行后的分析、讨论和整理阶段。**

这次整理没有修改应用代码、运行报告、启动学习、发布策略或改变业务数据。历史累计170,000,000 token授权仍是历史上限记录，不是本文件恢复运行的指令；当前余额须以运行账本为准。邮件已停止，百炼平台审计暂不进行。

## 阅读入口与证据边界

- [智能体与工具 prompt 完整明细](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/docs/reviews/system-design-and-requirements-20261017/agent-prompts.md)：角色原文、工具内部提示、动态拼装代码、注册工具与框架追加内容。
- [源文件与提取校验清单](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/docs/reviews/system-design-and-requirements-20261017/prompt-sources.json)：源码位置、文件哈希、提取文本哈希和作用范围。
- [用户报告反馈原话及来源汇编](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/customer-feedback-collected-20261016.md)：既有消息来源和格式标准摘录。
- [《报告编制格式标准》原文](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/format-standard-original-text.txt)：包括封面、扉页等例外。
- [Neo当前决策历史入口](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/neo/current-user-decisions-20261015.md)：按时间保存，前部旧预算／旧运行状态不能覆盖后部较新决定。

文中的四种标记：

| 标记 | 含义 |
|---|---|
| 用户已确认 | 用户明确提出或澄清的要求；不是实现证明。 |
| 代码存在 | 当前工作树有对应机制；不是对所有路径或业务效果的保证。 |
| 已观察 | 指定执行 trace、模型输入或产物中有证据；只覆盖该案例和版本。 |
| 讨论／待验证 | 候选设计、外部建议、尚未证明的效果；没有因为写进本文就自动生效。 |

本文基于当前工作树，基准提交为 b5525a3474b2f284f7a638f226be35a57d6e5d13，工作树已有未提交修改；具体内容以附录哈希为准。较早的 ARCHITECTURE、历史 ADK、native-rubric 和实验文档混有目标设计与旧实现，不能直接当作当前运行说明。本文不是重新完成了一次全库代码审计，也不宣称穷尽了所有历史 bug。

## 一、最终目标与需求适用范围

### 1.1 产品目标

生成专业、可追溯、符合委托范围和适用标准的**施工安全风险评估报告**。这一类别包括桥、隧、路、坡、涵；不能把本次边坡经验硬编码成所有报告的通用事实，也不能把类别要求只用在当前一份报告。

每份报告分别读取自己的：

1. 《报告编写范围说明》：合同段、评估对象、需要覆盖的内容。
2. 《提取大纲》：应从资料中提取和组织的内容。
3. 《报告编制格式标准》：字体、字号、页面、段落、表图和目录。
4. 适用指南和标准：评估对象、指标定义、分级方法、经验值、评分与表样。
5. 实际地勘、设计／一坡一图、现场核查、专家评审等证据：项目事实及其不确定性。

### 1.2 本次完整验证目标

用户的明确原话是：

> 仍按之间的plan执行，但不是执行fix的验证就结束了，给你5000万token预算，你一直迭代下去，因为现在用户的反馈已经来了，我们按照这个目标codex和Neo一直执行到最后一步，就是你的第一选项第一合同段全范围报告，按《报告编写范围说明》

因此，终点是**第一合同段全范围报告和独立问题清单 Excel，走完资料使用、正文、排版、实际产物及正常审核链路**。既有 OCR 是本轮主要输入起点；不是要求为了验证重复 OCR。局部修复、一次单坡测试、一个可打开的文件、Word／Excel配对完成，都只是中间结果。

### 1.3 首稿质量原则

用户要求：即使尚未审核，首稿也应与最终报告差距不大。Writer不能把已知写作、表样和排版要求留给Reviewer第一次落实。

用户提出的“类似幂等”包含两个不同要求：

- 操作层：重复调用、恢复和重试不能悄悄重复写入、消费预算或改变对象身份。
- 内容层：内部候选可以试错；宣称已完成的部分应符合已知要求和证据。报告可以有明确标示的未完成部分，不能把缺失、冲突或错误包装成完整正确结论。

这不是要求程序证明全部工程语义，也不是缺少一个章节就禁止一切内部草稿。它要求构建过程持续维持质量，而非完全依赖最后Review返工。

## 二、用户反馈与需求汇总

以下是有效需求及重要澄清，编号仅用于本文导航，不创建新的运行时检查项。报告反馈的原话出处见链接汇编；后续设计讨论以本会话直接用户消息为来源，不编造未提供的消息ID。

### 2.1 内容、范围与评分

| 编号 | 用户需求／澄清 | 落实时应保留的边界 |
|---|---|---|
| R01 | 本次第一合同段全范围，依《报告编写范围说明》。 | 不能自动缩为补Excel、配对导出或已写章节。覆盖清单独立于现有报告树。 |
| R02 | 提取与写作依《提取大纲》。 | 读取过大纲不等于每个章节或文字工具已获得并落实。 |
| R03 | 施工安全风险评估这一类别，跨桥隧路坡涵。 | 类别偏好、具体项目事实、某指南规则分开适用。 |
| R04 | 地勘和一坡一图逐对象核查，按指南文字先确定类型／分级档位，再选分值。 | 不按目标分数或风险等级倒推类型；缺依据不能猜分。 |
| R05 | 风化等级依据实际地勘描述，如强风化、全风化。 | 地层名称、风化程度与指南档位要逐项对应；不得只凭材料泛称选分。 |
| R06 | 同一指标计算冲突时参考指南经验值。后来明确是边坡指南第91页表格，不是公式。 | 让Coordinator或合适Agent解读适用指南并形成方法；不固化页号或一套权重用于所有工程。 |
| R07 | 总体风险三级及以下的倾向，以及确需四级应说明原因。 | 保留下面完整原话和例外；不能转成强行压分、删除不利证据或假造低风险。 |
| R08 | 重要结构物边坡也应纳入，如抗滑桩；不能只按土质30m／岩质20m常规高度筛选。 | 高度数值是用户提出的具体例子，适用条件仍需核对指南与项目资料。 |
| R09 | 查明K1320+380～760为何遗漏。 | 这是对象覆盖问题，不只是增加一句文字；需要核对该工点的范围和资料。 |
| R10 | 指标体系权重与分值表符合指南结构和内容；曾指定（S3-2-11-4-2）表与第11页示例。 | 第11页的表样要求与第91页的经验值方法不是一回事。 |
| R11 | 对应工点地质、水文等保留完整相关原文段落／图表，可用截图。 | 不能只摘支撑某指标的短句，遗漏限定、图注、表头或不利条件；也不是把整本资料全部塞入报告。 |
| R12 | 表格允许调整尺寸、分页，内容不变。 | 排版自由不等于改指标、注释、计算关系、列义或数值。 |
| R13 | 使用现场核查、专家评审、设计等实际证据。 | 项目人员真实活动与AI本身是否到现场不同；不得捏造活动、签名或工程批准。 |
| R14 | 引文客户可读。 | 源文件名称、位置和归属不能被source-XXX等内部ID取代；内部追溯仍需保留。 |
| R15 | 正文不应默认加入系统未到场、读取/OCR/模型过程等说明。 | 实际工程资料缺失、技术冲突和不确定性仍需如实表达，不因“专业口吻”删除。 |
| R16 | Excel独立于Word，仅向客户列出报告相关问题。 | 正常资料汇总、主要技术标准、常规recordbook不应假装成问题；确有需客户处理的缺失／冲突可列入。 |

风险等级的原话必须完整保留：

> 此外，总体来说，评估结果控制在三级及以下。但是不能打四级。如果实在需要大四级，要说明原因

这段话同时表达了等级倾向和例外。系统应依证据和指南给出真实判断；若实际结论触及例外，应说明依据并在必要时向客户澄清，而非静默篡改分值。

### 2.2 版式要求

下面是项目已提供标准原文的摘要，不是开发者临时设计的新模板。

| 对象 | 已提供标准要求 |
|---|---|
| 纸张和边距 | A4，210×297mm；上／下／左25mm，右15mm；装订线0，左侧。 |
| 字体 | 标题宋体加粗；正文宋体；英文和数字Times New Roman。 |
| 标题字号 | 一级小二、二级小三、三级四号、四级小四；对应第一章、1.1、1.1.1、（1）形式。 |
| 常规字号 | 正文小四、表格五号、页眉页脚小五。 |
| 行距 | 标题、正文、表格、目录1.5倍；封面／扉页的单倍、2.5倍等例外按原文保留。 |
| 段落 | 一级段前后各10磅；二级各0.2行；三级及正文段前后0；正文首行缩进2字符。标题悬挂缩进等按原标准。 |
| 对齐 | 封面、表格、一级标题居中；二级标题左对齐；三级标题和正文两端对齐。 |
| 目录 | Word自动目录，至少三级；目录题宋体三号加粗，条目小四、一级加粗。不要在子报告内重复插入全局目录。 |
| 表格 | 表题在上方、居中、宋体五号加粗；正文五号，数字／英文TNR；1.5倍行距；双线外框0.5磅；编号按原标准。 |
| 图片 | 图题在下方；标题、编号、注释字号及编号规则按原标准。 |
| 页眉页脚 | 页眉左项目名、右报告名，宋体小五；页脚从1起阿拉伯页码，TNR小五居中。 |
| 封面／扉页 | 项目名、报告名、单位、日期、负责人及资质各有独立字体字号行距，不能套一套正文参数覆盖。 |
| 细节 | 全角中文标点、数字和单位间空格、年份格式及列表编号一致。 |

用户对阶段报告的具体观察：边距、字体／字号没有落实；第15页与第25页又出现目录；行距不是1.5倍。这两个页码是用户观察，不能擅自换成我们渲染PDF的页码。

Layout通过工具参数落实已支持的能力；如果工具缺少表格行距或双线边框等参数，由开发者补足能力。Layout没有因为“负责布局”就获得修改程序源码的权力。验收需要Reviewer查看实际Word及渲染结果；配置正确、XML某字段正确、文件导出成功都不能单独替代视觉检查。

### 2.3 工作方式、权限与工程要求

| 编号 | 已确认要求 | 当前解释 |
|---|---|---|
| W01 | Neo代表用户习惯参与决策，Codex落实。 | Neo先判断问题是否成立、是否值得解决及顺序；检查源码、trace、实际输入与产物，不只读Main结论。 |
| W02 | 主动追根因。 | 出现问题不能只重跑或改提示词；区分typo、接口、共同设计和架构原因，并核对相邻路径。 |
| W03 | 类似错误重复出现应做共同设计优化。 | 不把多处补丁、增加更多guard或测试数量视为架构收敛。 |
| W04 | 参考《Code Complete》。 | 复杂度管理、信息隐藏、清晰接口、证据诊断、安全重构；没有核实持有全书，不伪造书中原文。 |
| W05 | 优先DeepAgents及兼容组件。 | 先查已安装能力，再选维护中的扩展，最后补领域差距；不自建第二套Agent控制循环。 |
| W06 | Agent决策与LLM文字工具分离。 | Agent仍要理解目标、章节与证据的语义关系，可按需读原文；独立工具负责有界的提取、对照、生成。 |
| W07 | 以最终交付目标验证。 | 单元测试、schema合法、工具能拒错、旧版保持不变，不等于模型能正确调用或客户要求落实。 |
| W08 | 一步步发现、解决，直到完整验证。 | 暂停受影响运行做根因修复可以是正确选择；改善的是修复完整性，不是一味减少停顿。 |
| W09 | 付费使用和无意义调用要如实记账。 | 保存原始请求／响应、实际usage、未知结果和重试；缓存token已包含时不重复加总。 |
| W10 | 列出全部已知问题及对应解决方案。 | 历史完整清单要能逐条查，不能用计数或几个分类代替；固定“已修复”状态也需要设计层回看。 |
| W11 | 保存用户原话供Neo学习。 | 保留出处和被新决定覆盖的历史；档案存在不证明未来自动遵守。 |
| W12 | 项目复杂度与需求匹配，清理多余文件和SQLite。 | Neo主导已授权清理；保留OCR、权威原件、必要恢复数据、付费证据和历史引用，不因哈希相同就任意删路径。 |
| W13 | 任务所需的视觉读取允许。 | 先前助手自行加的人员／签名页禁读限制被用户纠正；授权读取不等于可任意公开个人信息。 |
| W14 | 邮件停止；百炼审计先不用。 | 旧heartbeat中的ACTIVE和登录请求是历史，不能自动恢复。 |

## 三、系统设计：已确认原则与实际结构

### 3.1 三类职责

| 承担者 | 应负责 | 不应代替 |
|---|---|---|
| Agent决策循环 | 理解委托、选择资料与工具、判断策略、分解适量任务、采用或拒绝候选、解释缺口、选择下一步。 | 不能靠程序替它暗中选工程结论；也不能仅见“工具成功”就当内容正确。 |
| 独立LLM工具 | 在已传入材料和目标下完成有界文字提取、比较、生成、审查或图像分析，返回结果及限制。 | 不偷偷检索、委派、写业务状态、开新的模型循环或扩大权限。 |
| 确定性程序 | 输入输出结构、权限、身份、版本、保存、来源定位、计算、预算、幂等、错误和观测记录。 | 不把截断、默认值、隐藏工作流或错误措辞变成未经Agent判断的业务决定。 |

**分离原则本身仍成立。** 最新讨论指出的问题在实施：职责与决策所需信息没有界定完整，自定义包装和压缩过多，框架现有能力复用不足。不能把Agent需要读原文当成设计失败；也不能让它重复工具的所有工作，或要求每个角色全量读全部资料。

### 3.2 当前实际运行路径

当前原生路径使用DeepAgents。Coordinator可以委派Writer、Reviewer、Layout；这些是可用能力，用户没有要求每一份任务固定走完三人流水线。Learner独立、显式启动。旧ADK／native-rubric入口在当前build_agent入口被拒绝。

~~~mermaid
flowchart TD
    U[委托范围、客户反馈、原始资料] --> S[项目应用状态与版本化资料]
    S --> C[Coordinator 决策]
    C --> W[Writer 决策]
    C --> R[Reviewer 决策]
    C --> L[Layout 决策]
    W --> T[有界文字处理工具]
    R --> V[有界内容与产物检查工具]
    L --> E[导出、渲染与版式工具]
    T --> D[版本化内容、证据和关系]
    D --> F[明确版本的快照]
    F --> E
    E --> A[Word、问题Excel、渲染产物]
    A --> R
    V --> J[ReviewRecord与未完成项]
    J --> C
    C --> O[选定交付与清楚的局限]
    U -.显式反馈学习.-> N[Learner]
    N --> P[未发布经验候选]
    P -.经评估及授权发布.-> S
~~~

图示表示依赖和能力，不规定每次运行必须按箭头逐步执行所有角色。实际代码也有局部顺序约束，例如Coordinator提示中要求先拿到Review观察再决定依赖该结果的布局工作；这些约束应单独审视，不能用“动态Agent”一词掩盖。

### 3.3 数据与身份

| 对象／记录 | 用途 | 关键区别 |
|---|---|---|
| Requirement | 委托方要求及适用范围。 | 不从当前已经写出的内容反推全部需求。 |
| SourceArtifact／source版本与块 | 原始资料身份、内容、版本、位置。 | 源资料不是权限指令；文本块序号不是PDF物理页码。 |
| Criterion | 从要求形成可检查标准和所需材料。 | 有标准对象不保证检查声明充分；空或狭窄检查会漏掉需求。 |
| ContentNode | 报告、章节、段落、表格、图片等内容。 | body、qualifiers和claim_kind共同表达内容；限定不能在包装时失去可见性。 |
| Evidence／Relation | 引用、计算依据及内容关系。 | 存在链接不证明语义支持；“supported_by”之类结构还需要实际内容核查。 |
| DocumentSnapshot | 固定一组对象的明确版本及关系。 | 是版本清单，不是旧报告模板，也不是对内容的认可。 |
| Export／RenderArtifact | 指定快照导出的Word、Excel及可视化产物。 | 同一快照配对是版本一致性，不要求复刻旧布局。 |
| ReviewRecord | 对明确目标、标准、材料和产物的检查结果。 | completed、satisfied和工程验收是不同层次。 |
| HandlingRecord／任务与观察记录 | 处置、缺口、委派、执行与来源链。 | 已保存／已处置不能自动消除真实缺陷。 |

内容采用明确ID、版本、摘要和owner；修订不是无痕覆写。委派任务的作者身份由服务端绑定，LLM工具不会因为返回正文而获得新的业务owner。旧版本用于追溯、对比和明确复用；**用户目标从未要求为了复用而保持不合格旧版**。

应用业务状态与LangGraph会话checkpoint分开：前者保存内容和任务事实，后者保存控制循环历史。摘要和scratch文件不能改写权威目标、版本、权限或完成状态。

### 3.4 资料检索与材料传递

当前源资料catalog采用块存储及字面关键词匹配，未在本次主路径部署源资料混合RAG。既有可选Neo4j／向量知识能力不是“全部原始资料已经有语义索引”的证据。

- 原文分块保存；读取接口可分页、按明确source与位置恢复。
- 当前搜索对字面匹配敏感，同义词、别名、跨段关系和图表语义可能漏检。
- 源文本块页与PDF物理页是不同定位单位；视觉读取走对应原始页面工具。
- Agent可以持有观察引用，将授权的完整材料交给独立文字工具，避免在任务文字里重新抄全文。
- 引用可恢复不等于已读全；只命中若干片段不等于覆盖了完整对象。

**讨论方向**：关键词＋精确标识／范围过滤＋语义检索，命中后回到原文位置，扩展完整相关段落和表格。少量工程别名可补充，但大同义词词典不是前置条件。索引只帮助找到候选，不能证明事实、适用性或全范围覆盖。本方向尚未部署。

### 3.5 Agent与工具之间的I/O

当前代码已经使用Pydantic业务模型、类型化工具输入、独立文字结果校验、收据及原始返回保存；并非完全没有契约。问题在于不同层的结构、裁剪、错误提示和完成含义没有一致地覆盖Agent真正需要的判断信息。

一次交接至少需要说明：

1. 目标和适用要求是什么，不能只给一个输出schema。
2. 工具实际收到哪些资料、版本、范围；哪些尚未收到。
3. 结果是什么，存在什么冲突、限定、缺失，哪些结论不能作出。
4. 结果如何与材料、对象、原始返回对应，Agent如何检查和采用。

以上是责任分析，不是本轮新发布的固定字段契约。结构合法、ID存在、工具正常结束，不会自动证明内容正确。反过来，模型处理了程序缺陷后继续运行，也不能证明程序缺陷已消失。

### 3.6 排版、导出与审核

Layout读取范围、排版标准和选定版本，通过参数操作工具。当前有独立Word内容范围与workbook-only节点通道，使问题表不必被塞进Word正文；Word和Excel可以绑定同一快照。

Reviewer对委派的目标执行检查，内容语义与实际产物检查有不同材料要求。执行完成状态、检查结论、覆盖记账和最终选定交付必须分别理解。缺材料时应保留未执行／无法判断，不制造“检查完成且通过”。

最终验收不能只看数据或Word XML。字体显示、分页、表格、目录、标题和页面布局需要真实渲染观察。Reviewer的独立性也不允许它弱化标准或越权重写Writer正文。

### 3.7 反馈、经验与prompt指令的生命周期

| 通道 | 现有作用 | 不能据此推断 |
|---|---|---|
| 用户原话档案／Neo记录 | 开发过程中的需求历史与判断依据。 | 保存到Markdown就自动进入所有运行Agent。 |
| operator_feedback／任务应用上下文 | 将当前项目反馈交给决策角色。 | 工具一定接收了全部要求，或最终产物已落实。 |
| scoped instructions | 按system、report_category、project、report、assignment及角色筛选的版本化指令；处理显式覆盖与冲突。 | 能理解任意自然语言矛盾，或可越过权限／覆盖真实证据。 |
| Learner | 基于反馈与证据形成经验候选、记录处置；事实、偏好、方法分开处理。 | 运行一次就是有效学习，或候选会自动发布。 |
| 已发布经验上下文 | 在适用范围提供激活的偏好／策略和可发现的其他经验。 | “prompt里出现”就证明Agent采用、效果改善或可跨项目泛化。 |
| 可选GEPA实验 | 显式接入实验runner时评估／优化保存的指导候选。 | 正常报告每次必经；与原生Learner是同一个机制；可改事实或自动全局发布。 |

用户要求的“不要过窄”是学会辨别适用指南与方法；不是把一个工点事实泛化成所有报告规则。知识事实与行为策略应保留不同适用范围和发布依据。外部“学习检查项、自动收紧”等建议是参考，不能据此自动缩减用户scope或改变授权。

### 3.8 模型、摘要、预算与恢复

当前混合服务配置将Coordinator、Reviewer、文字／视觉工具映射到指定DeepSeek配置束，Writer使用glm-5.3，Layout默认回退Writer配置；显式角色配置可优先。配置束名称不证明一定直连官方服务，具体运行以保存的角色模型身份为准。本文不导出密钥或环境文件。

决策角色与LLM文字工具分离会减少部分重复上下文，但不会让决策历史不增长。Agent仍有目标、工具结果、任务、错误与决策轨迹，所以仍可能触发会话摘要。

当前stateful路径每次决策调用重新加入应用上下文，并使用项目WorkingSummary包装LangChain摘要中间件；摘要模型来自Coordinator服务。摘要提示目标约1200 token，输出上限16384不是触发阈值；触发和保留量由安装框架按模型profile计算，详见prompt附录。这里说的是本项目运行时，不能与Codex应用自身的会话压缩阈值混淆。

预算和恢复是确定性执行责任：调用前预留、记录真实用量、未知结果保留，不能把未知当零或自动重放；实际恢复点、对象版本和owner必须明确。存在历史绑定修复、调用计数和账本，并不证明已完成全部成本归因。旧运行终止后不会因为新heartbeat或本文整理而恢复。

### 3.9 工程组成与数据存放

| 层 | 当前组成与入口 | 状态边界 |
|---|---|---|
| 本地服务与工作台 | Python包、report-agent CLI、FastAPI webapp与static前端；提供项目状态、资料、运行、问题处理、内容交付和学习API。 | 现有操作入口，不代表完整产品验收；读取状态不应被理解成启动模型。 |
| Agent执行 | DeepAgents控制循环、委派与LangGraph checkpoint；项目middleware绑定业务身份、上下文和执行限制。 | 框架负责通用运行机制，应用仍负责项目权限和业务版本。 |
| 项目业务存储 | 各项目自己的SQLite state.db及文件目录；资料、内容版本、事件、分析收据、导出产物等保留可追溯关系。 | 独立于旧高速系统的可写存储；不能直接修改旧系统服务与数据。 |
| 会话恢复存储 | checkpoints.db保存会话与控制流历史。 | 不等于业务快照；保留checkpoint不是自动重跑授权。 |
| 经验库 | 按客户／项目与适用类型管理反馈、候选、版本和发布状态。 | 正文事实与偏好／策略的生命周期不同，不自动全局推广。 |
| 导出与渲染 | python-docx、openpyxl及PDF／图像工具等；真实文件、结构和渲染观察分别记录。 | 软件能导出不等于内容、视觉或工程语义通过。 |
| 知识能力 | 可选Neo4j／向量相关模块。 | 不能把依赖已安装等同于本次主路径已接入源资料语义检索。 |
| 研发证据 | .analysis、.runs、.memory和docs保存调查、实验、交接与设计。 | 这些目录含历史记录，不应形成多套互相矛盾的当前任务状态。 |

已核对的安装版本包括DeepAgents 0.7.19、LangChain 1.4.2、langchain-core 1.6.5、LangGraph 1.2.12、Pydantic 2.13.5及langchain-openai 1.6.6；项目依赖声明另见pyproject.toml。版本是环境事实，不是框架替我们完成业务设计的证明。

历史清理已对部分终止案例的重复请求事件归档。全历史调用／成本审计必须读取相应完整归档，不能只统计已压缩的在线数据库。共享不可变资料、减少镜像和统一物化是持续收敛方向，不能宣称已全面实现；本次没有进一步清理文件或数据库。

## 四、智能体设计明细

### 4.1 报告运行时角色

| 角色 | 输入与决策责任 | 主要能力 | 边界和输出 |
|---|---|---|---|
| Coordinator | 当前完整目标、委托scope、需求、资料、任务观察、预算、反馈；决定策略、委派、覆盖、继续或请求人工信息。 | 查资料与状态、形成标准／关系、委派、版本选择、快照与交付协调。 | 不冒充Writer写正文或Reviewer给通过结论；不能为方便而改小用户目标。输出保存的决策对象、任务和交付状态。 |
| Writer | 本人任务、适用要求、实际证据、结构和待修订节点；判断章节逻辑、材料充分性与候选采用。 | 读取／分析资料，调用process_report_content，按收据保存本人节点及证据。 | 独立文字工具写实质内容；Writer仍负责理解和判断，不能只拿ID提交。保留限定与不利事实，不改他人owner。 |
| Reviewer | 明确目标、snapshot、标准、required checks/materials及独立证据；决定检查和后续补材料。 | perform_assigned_review、perform_assigned_artifact_review及受控读取／计算／视觉能力。 | 实际系统提示是ORGANIZER_PROMPT；检查工具的TOOL_PROMPT是另一层。保存真实检查结果与缺口，不越权修正文或自行宣称工程验收。 |
| Layout | 当前指定快照、报告格式标准、相关渲染及Reviewer反馈；选择表示参数和适量验证。 | 版式配置、Word／Excel导出、渲染观察、提出工具能力缺口。 | 不改工程事实、分数、来源或标准；不以自身检查替代独立验收；不改源码。 |
| Learner／experience_optimizer | 明确反馈及其版本、证据、已有经验与评估结果；决定可学内容和候选表达。 | 读反馈／证据／候选，必要时调分析工具，propose_experience，记录feedback disposition；有显式runner时可优化实验。 | 非每次报告必经；候选默认inactive；不能自动发布、修改原报告、事实、权限或模型。 |

### 4.2 有prompt但不是自主Agent的组件

| 组件 | 目的 |
|---|---|
| process_report_content及相关文字工作 | 在所选材料、任务、目标schema下生成有界候选。 |
| Evidence analysis | 对明确材料做提取／分析，返回带来源及限制的结果。 |
| bounded review checker | 执行已经交付的检查任务，保留材料、结论和无法完成的项。 |
| artifact review checker | 面向实际导出／渲染产物的有界检查。 |
| Vision | 解释指定图像／页面；不因调用成功就算整份资料已看完。 |
| WorkingSummary | 压缩工作历史用于继续，不改变应用权威状态。 |

这些工具可能调用LLM，但没有独立的长期目标、任意委派、业务写权限和开放循环，不能因为存在system prompt就统称Agent。

### 4.3 开发协作角色

Neo代表用户已表达的习惯与最终交付目标，负责问题成立性、优先级、设计取舍和根因判断，并检查源码、真实trace与最终结果。Codex Main负责调查、实现、验证和交付证据。其他审阅者提供具体证据，由Neo作相应判断。

Neo不能扩展用户预算、发布权限或工程签字权；也不是报告程序中的强制运行时审批Agent。本文没有声称Neo是用户本人，或能完美复制用户所有想法。

### 4.4 Prompt如何组成

不能用一段role prompt代表一次完整模型输入。当前要分七层：

1. **角色基底**：common＋角色文件；Reviewer在当前路径被ORGANIZER_PROMPT替换；Learner有独立规则文件。
2. **框架／中间件接口**：角色基底之外的系统提示和工具schema。安装版本的文件系统／委派默认不重复加入整段使用说明，主要经工具描述提供；Coordinator显式todo中间件会追加系统提示。具体文本见[框架附录](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/docs/reviews/system-design-and-requirements-20261017/framework-prompts.md)。
3. **服务端当前应用上下文**：goal、scope、owner、assignment、当前版本、反馈、预算与剩余检查。
4. **外部已生效指令与经验**：按角色和scope筛选；候选和历史指令不应自动生效。
5. **本轮用户／委派消息和历史**：包括工具观察与必要摘要。
6. **独立工具内部prompt及材料packet**：工具不会自动继承Writer完整阅读历史；需通过所选引用传入。
7. **模型适配后的实际请求**：最终role/messages/tool schema才是本次调用证据；原始文本、配置名、prompt_hash都不能单独代表完整输入。

附录提供静态原文和动态拼装源码，不宣称所有checkpoint都收到同一份有效prompt。尤其当前部分Reviewer身份元数据仍取content-reviewer文件哈希，而实际build_agent使用ORGANIZER_PROMPT；因此不能据该哈希证明有效输入是什么。

## 五、已经观察到的关键缺口

本节是与设计直接有关的事实与局限，不代替既有完整bug清单，也不把历史缺陷数量当作当前未解决数量。

| 主题 | 证据与已确认机制 | 当前应如何理解 |
|---|---|---|
| 目标缩减与旧版复用 | 10/16调查发现Coordinator实际指令转向补Excel／配对导出并复刻旧R6布局；用户未提出复刻R6。 | 版本一致性不能替代当前目标达成。报告快照本身不是要求复刻旧版的原因。 |
| 格式未落实 | 格式标准已在后续有效输入出现，但Writer生成的Layout参数仍为四边25mm、正文1.3、表格1.15、目录2级等；导出按这些错误参数工作。 | 不能仅归因“从未读到标准”。新旧Word一致性检查也不等于标准符合性。 |
| 重复目录 | 嵌套report节点使导出器重复生成目录；已观察Word内有多处目录。 | 是具体程序／内容结构交互问题，不应留给客户发现。 |
| 选材料受程序信号影响 | 超过64000字符的所选证据被TEXT_WORK_SELECT_SMALLER_LOCATED_EVIDENCE拒绝；错误建议会影响Agent后续缩小选择。 | 这是整次拒绝，不是“最多两份资料”规则，也不是静默截断已选packet。 |
| 决策返回信息不足 | 某些历史返回把原文字段仅展示240字片段，正文／限制未充分呈现；Writer可能仅凭收据采用。 | 原始内容保存着，不代表Agent实际获得了足够判断信息；可恢复也不等于已恢复。 |
| 工具输入与决策投影混淆 | 对已追踪的1133→1136→1137及1203→1206→1207两条链，所选材料到独立工具保持一致。 | 不能说程序剪掉了原PDF，或在这两条链中静默删掉工具已选材料。裁剪发生在Agent可见投影等具体层。 |
| 端到端验证误判 | 组件测试、格式拒错、保存成功、导出一致性、局部review被当作更大范围进展。 | 正常内容／版式审核和第一合同全范围覆盖尚不能据此宣称通过；该次调查case的ReviewRecord为0。 |
| 反馈与生效不等价 | 原话、候选、注入、采用和产物效果是不同环节。 | 不能因为“学习输入已保存”就说反馈已落地，也不能因一次case成功就泛化。 |
| 程序问题被Agent绕过 | 程序拒绝／裁剪后Agent改策略继续，最终可能得到表面成功。 | 必须保留首次偏差及影响链；成功继续不等于底层设计正确。 |

详细证据：[布局与生成质量RCA](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/neo-trace-review.md)、[R6布局来源](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/r6-layout-origin-root-cause-20261016.md)、[材料转换对照](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/table-material-program-transformation-proof-20261016.md)、[Guide表格执行RCA](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/guide-table-execution-root-cause-20261016.md)、[原始省略文本](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/omitted-tool-return-verbatim-20261016.txt)。

## 六、已经讨论、但不能写成完成的调整

| 方向 | 讨论共识／建议 | 未完成事项 |
|---|---|---|
| 明确Agent／工具／程序边界 | Agent保留语义判断；工具做有界实质工作；程序做确定性职责。 | 全部路径是否符合、哪些重复层要删除，仍需按实际执行审视。 |
| 统一I/O责任 | 输入、结果、局限、材料覆盖、错误含义与原文恢复应清楚一致。 | 尚未完成新的统一协议迁移及全链验证；字段齐全也不等于语义充分。 |
| 框架优先 | 复用LangChain工具schema、结构化模型输出、ToolMessage artifact、middleware等。 | 不是选一个组件即可自动解决业务契约；strict／provider能力需按实际版本验证。 |
| 资料混合检索 | 字面与语义检索结合明确定位，命中后恢复完整上下文。 | 当前源资料主路径尚未部署hybrid RAG；检索召回与覆盖效果未验证。 |
| 构建时质量 | 首稿执行已知需求，Reviewer独立发现剩余问题。 | 不靠增加末尾审批环来替代前端正确构建；实际首稿仍需证明。 |
| 验证保留故障信号 | 关联程序原始返回、模型可见输入、Agent策略变化、最终产物。 | 不把Agent自愈当系统通过；仍需能识别漏项和错误是否被掩盖。 |

用户提供的backup目录技术文档是参考资料，不是自动改写本系统规则或证明主项目已实现。特别是其中历史扫描数量、budget未接线等说法，应核对对象、时间、版本；“全部supported_by缺失即全部报告无依据”也需要考虑检查定义和抽样语义证据。

平台能力与边界：DeepAgents的response_format主要约束Agent最终structured_response，不自动统一每个工具输出；LangChain的工具args_schema约束参数，模型with_structured_output约束模型返回；ToolMessage.artifact可保存模型不可见原始材料，但不能省略决策必需信息；middleware提供公共接入点，不替我们定义正确业务含义。相关官方资料见文末。

## 七、近期讨论保留

以下原话来自当前会话，尚不能声称已全部进入既有659／81条历史档案。本文保存这组后续澄清，不改写旧记录：

> 我们对返回结果的结构化约束不强

> 我们自己做了很多工作，deepagents或者第三方开源框架是否有支持这个的？

> 所以并不是设计的问题，分离是支持的，而且有工具，是程序过多的干预了本应有平台处理的内容

> 我想了一下啊，还是你的问题，因为这个设计原则本身并没有错，但是你在实施的时候一没有充分利用平台已有工具，二没有考虑周全。这样配合，会有无穷无尽的问题

> 我觉得现在这些问题弥散在整个系统里，程序与agent的职责纠缠，工具与agent的职责纠缠。导致系统非常的复杂不够简洁。其实我已经发起多次的coder review和design review，但是仍没有解决问题，还有很多隐藏的陷阱。这个真的有些麻烦

> 本来，这次花费一个多亿的token就是为了通过实际数据的验证来暴露问题，但是我们这个系统有一个特点就是程序引入的错误被agent处理过之后，就很难发现问题了。所以错误埋的更深

这些反馈要求后续设计审视实际责任和组合行为，保留原始故障证据。本文不把它们简化成“换框架”“加更多guard”或“再跑一次就能解决”。

## 八、源码和记录导航

| 主题 | 主要入口 |
|---|---|
| 当前开发约束 | [AGENTS.md](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/AGENTS.md)；[架构文档，含目标与历史内容](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/ARCHITECTURE.md) |
| 运行控制与角色构建 | [deep_runtime.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/deep_runtime.py)；[角色与工具绑定](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/hierarchical_tools.py) |
| 模型服务 | [model_config.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/model_config.py)；[deep_models.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/deep_models.py) |
| 动态上下文／摘要 | [task_context.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/task_context.py)；[working_summary.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/working_summary.py) |
| 文字工具与采用 | [text_work.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/text_work.py)；[独立文字工具说明](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/docs/independent-text-tools.md) |
| 决策投影 | [decision_data.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/decision_data.py) |
| 审核 | [bounded_review.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/bounded_review.py)；[artifact_review.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/artifact_review.py) |
| 资料读取／检索 | [catalog.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/catalog.py)；[source_search.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/source_search.py) |
| 学习 | [learning_runtime.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/learning_runtime.py)；[反馈学习说明](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/docs/feedback-learning.md) |
| 指令版本和适用性 | [prompt_instructions.py](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/prompt_instructions.py)；[说明](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/docs/prompt-instructions.md) |
| 用户原话 | [最初档案](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/neo/user-statements-20261014.md)；[Neo创建后补充](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/neo/user-statements-since-creation-20261015.md)；[当前决策入口](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/neo/current-user-decisions-20261015.md) |
| 历史问题清单与设计复核 | [逐条bug清单](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/full-chain-acceptance-20261014/complete-bug-inventory-20261015.html)；[实际设计复核](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/.analysis/full-chain-acceptance-20261014/actual-design-review-20261015.html) |

框架资料（能力参考，不是本项目完成证明）：

- [DeepAgents结构化最终输出](https://docs.langchain.com/oss/python/deepagents/customization#structured-output)
- [LangChain工具schema](https://docs.langchain.com/oss/python/langchain/tools#advanced-schema-definition)
- [模型结构化输出](https://docs.langchain.com/oss/python/langchain/models#structured-output)
- [ToolMessage与artifact](https://docs.langchain.com/oss/python/langchain/messages#tool-message)
- [自定义middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom)
- [Pydantic校验器](https://docs.pydantic.dev/latest/concepts/validators/)

本文的交付对象是这份可追溯总结及prompt册。是否重构、恢复付费、改写报告或发布经验，不能由本文件自行推出。
