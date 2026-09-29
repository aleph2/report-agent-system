# Task028 scope diagnostic 独立评审

Reviewer：`postrun_review`。本节为调用结果前的冻结输入核验；未读取模型输出，后续按Main完成通知另追加实际公开判断。只读Task028任务包、准备脚本、runner及冻结材料，并复用已核实原始设计p97视觉参考；额外只读原PDF提取几何校验。未调用模型/网络/凭据，未改运行、fixture、来源或实现。唯一写入本文。

## P3-028-I01：无工具诊断材料仍带有可调用原页入口的表述

自动compact view保留`raw_geometry_access.tool=inspect_source_page`和note“Original per-cell bounds remain available with the same source ownership/hash checks.”；但本runner的`create_agent(..., tools=[])`、settings `evidence_tools=[]`明确没有这个观察工具。原系统中这一locator有效，在当前静态诊断中只是来源能力描述，不能实际调用。模型若按字面期待补查，可能误解当前可获取证据的边界。

P3，影响诊断元数据准确性，不是原表损坏或权限绕过。四格同带该指针，system也明确无工具时据给定内容判断；正确列义和全部必要数值已在输入内，因而不阻断本次隔离诊断，也不要求为此修改冻结输入或重新跑格。Main在解释结果时明确“静态包，不可调用补查”；实际输出若声称调用inspect/视觉复核，须单列无据动作声明。不能仅因指针存在便认定模型已经被误导，亦不能把诊断归为自主取证成功。此处保留generic代码原样比为一格特殊修改更有可比性。

## 冻结输入核验结果

| 检查项 | 独立结果 |
| --- | --- |
| 四格身份/顺序 | `30e4c1f260a1` original/broad；`264926551e6a` corrected/local；`a725e7816f27` original/local；`fb42eb2d7e0b` corrected/broad。reference只用于评审，runner不读取labels/reference。 |
| 原稿完整性 | 两个original均26,256字符、SHA`7e86b61aa246f5f6b08ecd60c546a95c67cf88f9929f41462285c5c5eddea28d`，与已确认原稿一致；不是只给局部摘录。 |
| 单处测试修订 | 两个corrected均26,255字符、SHA`2c5b5309e412d25a156fe5f5b8d03fbd96f8d53c306bd6e9f2771dbb44b5f562`。独立确认原稿恰有一次`40 块沉降板`，仅替换为`6 块沉降板`后与corrected逐字相等。原6个F值与其他缺陷不变。 |
| 相同候选跨职责 | broad/local对应candidate逐字相同；source、rubric、system均顶层共享，不因scope重复拼写造成内容漂移。 |
| scope出处 | broad逐字等于Task022原assignment；local逐字等于Task020原英文委托。两种scope都排除导出版式/工程签发；local将职责限定为§5.2.3(1)括号内合计数量及对象，并明确其他章节、未引用项目和等价计量单位文字不构成必交要求。 |
| 29段证据 | `source.excerpts`与Task022冻结对象完整逐项相等，共29段。不是改成针对40/6的人工整理段，也未删除可能分散注意的其他摘录。 |
| p97自动rows | 当前compact的rows与Task022 raw表rows精确相等，含所有空串/null及原列序；源id、文件hash、页码、页框等共同元数据保持。generic limitations说明更新不改变值；compact另有结构和raw-access元数据，不能称整个view字节相同。 |
| system/rubric/source | 文本SHA分别为`85caa16ad32d6ba3a8c772564ffc36a2e73e3e711594e9e0018ec37c71979476`、`b63e7620378e6648fa9882db5c69e978a9744e0a5c095c1db0642792abc70ca5`、`a01dd4de092b2ffbab0a8a32e7f0a6916e630c04da6cd9e95f067b8d2b9d99fc`，均独立匹配hashes。 |

完整共享source字符串103,118字符。按实际`user_message`函数独立重建四格消息，字符数分别132,329 / 132,091 / 132,092 / 132,328，全部精确匹配冻结user_sha256。长度差仅来自已声明委托范围文本及单字符数量修订；local不是较短候选正文。职责聚焦也自带§5.2.3定位和任务语言变化，不能宣称完全隔离了抽象“责任感”或模型内在注意机制。

## 原件与几何独立核对

只读`.runs/task027/native-compact/sources/第1合同段 第二册 路基、路面 第一分册(3).pdf`；其文件SHA独立重算为`74ab4e22761aea5d4130677ff50ffe0505676d27daa1fa48ca20eecdf0d96df6`，与输入的source_sha256一致。pdfplumber按同一line/line设置读取物理p97：全部**484个完整单元格矩形**与compact x/y轴及`[r,c,rowspan,colspan]`解码出的集合精确相同；rows与table bbox同样精确相等。该验证直接用原PDF，不调用应用converter生成另一套预期。

原表两行表头将管长(m)、测斜管个数、沉降板块数分列；合计行为位移桩96、C15砼2.892、位移钉96、测斜管800 m/40个、沉降板6块/C25砼0.072、测力计96。本文复用Task019已独立视觉核实的列关系；这段评审标签不会拼入模型输入。报告引用的四个对象应分别对应96、800、96、6，其他表项未引用不构成local遗漏。自动几何是可定位观察，不等于PDF所有语义经程序认证。

## runner与实验边界

- `load_inputs`在加载凭据前验证schema、hash及current calibrated reviewer_prompt/load_rules一致。factory确实以冻结system_prompt创建模型agent，工具为空，response_format为native GraderResponse；不是只记录正确prompt却给模型另一个prompt。这里只核对代码路径，实际模型/参数/system及完整输入仍待运行I/O逐格确认。
- `run_case`以唯一目录保存输入、receipt、公开audit，再调用一次外层agent；无作者、无native修订循环，不读取评分reference。框架可能为结构化格式恢复产生后续响应，实际是否发生须看公开trace，不能预称每格只有一条响应。响应schema工具不属于来源检索工具。
- 本诊断不是原项目委托的静默修改，也不是工程审批；local的通过只能用于该数量核查范围。corrected全稿仍保留F02/F03/X21/N01等问题，broad satisfied不自动算正例；同样，broad发现其他真问题但未提数量只能计其他发现、目标未提，不能因needs_revision就自动记40/6命中。
- 这是已知开发样本，不是新盲测。与Task019/020旧GLM、手工列义材料不能唯一归因某一个因素；与native027相比也改变了证据取得方式、上下文组织和任务设置。所能直接比较的是这四格之间、相同自动供给证据下的scope/候选条件。
- Main说明准备中两次assert失败发生在冻结/调用之前（文字顺序与limitations更新），本文已查看最终准备脚本及冻结结果，不重演失败或改历史。最终不变量现已独立成立；无证据据此推断已经发生付费重试或样本随模型结果调整。

## 初步处置与冻结记录

独立检查freeze列出的36个文件当前SHA全部相等。inputs文件SHA`b6a94c926c4b78c5a0ff2fce67f312e0d506a7cf8778bdc04bb8887951af2755`；reference SHA`c004ba33797d0e4d2c062cd04232e7844088c2b0eda29fc8f205fcc70987ba9b`；freeze SHA`f6dacb91d3cfb63c950e4c03a6f24e9817db43a91a10a348c5182d416c542f64`。

未发现阻断已授权隔离四格诊断的输入内容缺陷；P3-I01需如实记录能力界限，不是停工命令。输出评分待Main完成通知后追加，按明确匹配/明确不匹配/泛称匹配/未提及/误指控，以及修复边界和整稿接受分别记录，不用顶层标签替代证据判断。

## 2026-09-29 调用前协议澄清及前两格评分

### P3-I01已控制：四格统一说明raw locator不可调用

Main在付费调用前加入统一前缀：`Only the supplied report and source evidence are available. No retrieval or export-inspection tools are available. raw_geometry_access entries are provenance metadata, not callable tools in this session.`。独立比较当前inputs与保留的`inputs-pre-protocol.json`：顶层system/rubric/source/experiment/hash不变，每例id、顺序、历史assignment和完整candidate不变；只有按共同前缀重建的user_sha256改变。原始scope正文没有改写成新的偏向性委托。

当前inputs SHA为`4d6e9a663392badcac341139f0f2828858324c23e1e4276524fe930010ae1265`；上述调用前输入核验保留历史，不再将旧input/user哈希当作本轮实际值。runner的`diagnostic_assignment`对四格加相同前缀；缺少成功调用输入audit现在触发`ACTUAL_INPUT_AUDIT_MISSING`，不会把无审计当成匹配。只读现代码确认这些保护，未运行新调用或更改冻结文件。P3-I01由明确的当前能力说明控制，不再视为未缓解阻断；静态包仍不是自主取证。

### P2-028-O01：original/broad在目标反证已提供时全通过

`30e4c1f260a1/output.json`为satisfied，五项均true；公开理由重点确认正确F算术、来源引用与阶段限制，**没有提及40/6或明确判断四项监测数量**。目标分类是“未提及”，不是“已认对”、也不是Task026式明确肯定40。

该格实际输入含完整原稿及设计p97自动compact表。原稿§5.2.3(1)40块沉降板与表的沉降板6、测斜管40可直接核对；“有些事实不在所给摘录内、此处不可验证”的一般限制不能用于这项已经提供的反证。原稿F03/X21/N01的规则/输入与实施状态矛盾也已随全文到达；其“chosen inputs ... correct, justified and internally consistent”和未夸大work performed的肯定过宽。F02仍需区分：本包没有地勘p20/p137/p142，但报告自己列候选、排除/待确认及全部覆盖的表述已在；不能把给了K1321理由当作全部候选范围得到有据处置。

P2，影响整稿可靠性判定；阻断把该输出当作本稿质量通过或监督体系可靠性的证据，不阻断隔离诊断继续。生产方需纠正已可判定的派生错列；Main保留失败，不通过重复格择优。没有作者调用，不能声称错改、修复或工程使用已经发生。

### corrected/local：目标明确匹配，有据的受限接受

`264926551e6a/output.json`为satisfied，公开逐项确认**96位移桩、800 m测斜管、96测力计、6沉降板**，定位设计PDF物理p97、S3-2-10第3页“第1合同段合计”。它也明确测斜管40个、位移钉96个是未引用项，不要求本委托额外补写。对象识别、目标事实及局部接受均正确，不是仅凭satisfied或静默通过计正例。

列出的源表分项加总12+45+16+6+8+9=96，360+160+80+80+120=800，6+24+18+24+24=96，沉降板仅K1319行6块，均可由实际给定表支持。它明确其他报告内容不在结论范围，没有把单处更正宣称为整稿修复或工程签发。原稿其余已知缺陷不构成本次local误拒要求。

### P3-028-O02：corrected/local附加支持理由的来源归属和适用范围不准确

- 该格两次称这些分工点数量是“report's own per-工点 values”。实际完整candidate只有括号内四项合计，不包含上述逐行监测数量；分项来自所给**源表**。数量和加总成立，但所声称的报告内部交叉核对来源不准确。
- 它以“C15 0.032 m³/pile”辅助证明列义。多数行确为0.032，但首行12桩对应C15为0.204，即0.017/桩；该比率不是全表统一性质，若套到全部96则3.072也不等于表合计2.892。报告的0.2×0.2×0.8可算0.032，但不能代替解释源表首行差异。20 m/管、0.012 m³/板在有值的对应行/合计可支持；几何提取不因此变成所有工程量均已验证。

P3，额外论据归属/适用范围过头，不推翻四项合计与列头直接匹配；未据此给出错误修订要求或拒收，当前没有传播到报告。Main在结果中保留局部命中与理由瑕疵，不据此要求扩大委托补核全部混凝土量。阻断把“报告本身提供分项”或“全表统一C15比例”作为核实事实复用，不阻断局部判别计为正确。

### 前两格实际输入、参数及动作证据

- 独立直接读两格model-io首请求：均只有system和human，无历史。system均3,343字符，与当前冻结system逐字相同，SHA仍`85caa16a…979476`；human分别132,534与132,296字符，逐字匹配各格input.json，hash分别`b300742fc5fb7c80200bbc982a12e71ea3fa2143bd02c53db2f2844bf1cee5da`和`4788230608255398acee843c005ae7cc8d51500e9d5d7123c06a03537270f159`，匹配当前冻结user_sha256。共同availability前缀、完整source字符串及完整candidate均实际到达。
- 两格settings完全一致；实际`diagnostic_invocation.parameters`也完全一致，模型deepseek-v4.1-flash、thinking开启、high、非stream、非并行、65536输出上限。回调层字段是max_completion_tokens，payload构造/settings字段是max_tokens；没有HTTP抓包主张。实际唯一工具schema为GraderResponse，不能把它当作检索/算术工具。
- 各格恰1个请求、1个响应，无格式恢复；公共response没有任何原页查看/导出工具调用。局部“Column identity was verified”可以指对已给列头和数值的文本核对，不自动等于虚构执行inspect；没有证据支持声称实际看过图片。广域“I independently recomputed”同样是模型公开运算主张，六个最终F值既有验证正确，不能因无calculate就断言它必然没计算；也不能拿该主张替代输入/材料性判断。
- receipt实际用量分别85,502与67,180 tokens（计total_tokens，不重复加reasoning_tokens）。当前freeze所列文件独立hash均匹配。未读后两格在途输出，也不据首两格跨候选比较就宣称local稳定优于broad；还需完成original/local与corrected/broad配对。

目前可记录“原稿broad漏报目标且过宽接受；修正稿local明确匹配且受限接受，伴两处附加理由瑕疵”。整轮判别效果、scope方向和下一设计结论待四格完整后再定。

## 第三格 original/local：明确检出，修订边界另有缺陷

`a725e7816f27/output.json`为needs_revision。公开解释及Correctness gap准确指出：设计物理p97/S3-2-10第3页“第1合同段合计”中40是测斜管个数，800是管长，沉降板为6块并有C25砼0.072 m³对应；原稿把40误归沉降板。另三项96位移桩、800 m管长、96测力计正确，个/根的等价计数措辞未被误拒。目标评分为**明确不匹配、事实识别正确、需要纠正的材料性判断正确**，并明确要求改为6块。它没有因为阶段性或缺工程签发而接受已知错列。

### P2-028-O03：把未引用源项强制纳入修复，超出明确local委托

最终explanation仅条件性提“if ... meant to be complete”，但实际失败criterion的gap更强：因括号有“合计”，要求改6后还须“either add 位移钉96个 and 测斜管40个 ... or drop the completeness claim”。委托原文明确：**Source-table items that are not quoted ... are not deliverable requirements for this commission.** 原稿“合计”在列举的四类监测对象语境中表达各自总量，并没有声明已穷尽表中所有设备/混凝土项目。仅凭这个词，不足以新增完整列举所有源项目的要求。

未引用的位移钉96、管数40本身有源支持；问题不是这些数值虚假，而是把额外加入或删除“合计”作为修订必须满足的条件。该要求可能驱动不必要的内容扩充或文字删除，并把“原错误已纠正”误判成仍未完成委托。正确修复最少只需将40块沉降板改为6块，其他三合计和合法范围可保留。此前corrected/local恰在保留“合计”且没有新增这两项的同一正文上正确通过，也证明不能用本gap倒推一个已冻结的必交项。

P2，局部反馈范围/修复标准可靠性缺陷，**不推翻40/6的正确检出和needs_revision**。没有作者执行，因此不声称已经出现错误改稿或工程后果。阻断把本格反馈完整复制为新的强制需求、或宣传已证明可靠修订闭环；不阻断此格目标命中、其他已授权诊断或待审结果交阅。Main保留反馈与委托边界，生产方只按有据缺陷修正；不为了满足模型临时要求扩展原任务，也不因该P2停掉独立最后一格。

### 第三格实际输入及阶段结论

- 直接读实际model-io：1请求/1响应，system与当前冻结逐字相同；human132,297字符，SHA`7f3da34c6e148ba83c7d3fc79446ccfdde5f59026b371b7dedabe0ea7039cc85`匹配当前冻结/input/receipt。统一availability说明、全部source和原稿正文均到达。
- settings与corrected/local完全相同，实际diagnostic回调参数也逐项相同，仅GraderResponse schema，无来源或执行工具。回调字段与payload字段层级沿用上节区分。receipt用量77,097 total_tokens，无补发/格式恢复的公开响应。
- 此时local正负配对都给出了明确正确目标判断；original/broad仍是漏报目标且全通过。但本节未读取最后corrected/broad输出，不把三个格当完整四格结果，也不把已知开发样本的一次局部成功视为自主发现或一般可靠性证明。局部成功与P3-O02/P2-O03反馈缺陷同时保留。

## 四格全部完成：corrected/broad及完整结论

### 最后一格的有效发现与解释边界

`fb42eb2d7e0b/output.json`为needs_revision，Scope及Human authority失败，另外三项通过。该候选只更正沉降板数量，其他问题仍在，不能把它预设成整稿正确正例。

- **F02真实检出**：输出准确指出原稿§2.4.5列出的K1318+235～740右12 m与K1324+500～560左右26 m，既没有评分，也没有在§1.3.3说明各自排除/待定理由及影响。这个矛盾可直接从已给完整稿内定位，不需要假称本次已获地勘p20/p137/p142。要求核对候选与范围、说明理由影响或缩小过强覆盖主张，有据且可修订；不是要求所有候选无条件新增评分。
- **3.1.2(2)措辞须限制理解**：其“Reconcile every 3.1.2(2) candidate”把两处放在同一筛查措辞下，但给定指南物理p12明确第(2)类为不良地质地段开挖形成的**不足20 m**边坡。26 m不能仅因潜在不稳定就自动满足该条，原稿28.9 m工点采用类似理由也不构成原文规则。此gap使用candidate并允许有据排除/缩小范围，没有明确命令26 m按第(2)类纳入，因此不直接重判成Task025那种已断言错误法定归类的误报。生产方仍须保留高度条件及真实适用依据；不能把此句当作Reviewer已替项目裁定所有候选符合第(2)类。
- **N01现场活动状态真实检出**：§1.2(8)采用评估人员现场调查资料，§3.1总句“本次…流程实施”下列成立小组、进行现场调查与核查，§6.1(3)却承认尚未系统开展、待进场补充。模型要求统一成计划/待做或移除无据完成表述，符合准确报告当前工作状态的任务；不是强制本次去做现场调查。
- **专家评审部分只宜作时态澄清**：§3.1(7)原句为“经专家评审…后形成最终评估结果”，同时§6.2(8)明确“尚需…评审”。前者可理解为程序条件/后续顺序，而非独立的“已经通过评审”断言；§3.1总句又让全段完成状态存在歧义。输出建议标记计划/待做可以消除这种歧义，但explanation把expert review一概说成“as done/used”比原句能确定的含义更强。本文不将其单列为已确认伪造评审/擅获审批，也不因为这种概括过强推翻已有现场调查矛盾与拒收依据。

最后一格没有明确讨论监测四合计，所以目标分类仍为**未提及**，不能把needs_revision当作40/6检测命中；同样，不能把未提目标当作它没有任何有效审核能力。它发现了两个与数量更正无关的真实问题。

### 重要残余：Correctness通过范围仍过宽

该格认可六个F算术有既有证据支持，但其Correctness条目还肯定chosen inputs/rule applicability全部有据一致。F03的较完整分档35/30、缓于自然坡取正角差档，以及X21的残积软弱地层R60与自列75～100关系都仍在全文且未解释。这是P2-028-O01所述过宽正面判断的另一表现；**本格顶层已经正确要求修订，并非另一份整稿false accept**。应保留“发现了足够拒收的真问题”与“其他明确通过项仍有反证”两个评价，不能用任一项抹掉另一项。无作者修订，不能把未列的残余记作以后必然未修复或已经修好。

### 四格证据表

| Candidate / scope | 实际result | 监测目标公开判断 | 其他真实发现 / 限制 |
| --- | --- | --- | --- |
| original / broad (`30e4c1f260a1`) | satisfied | 未提及 | P2-O01：完整证据下仍过宽全通过；六F算术正确不支持全部输入正确。 |
| corrected / local (`264926551e6a`) | satisfied | 明确匹配96/800/96/6 | 正确受限接受；P3-O02附加出处/比例旁证瑕疵，不扩张为整稿通过。 |
| original / local (`a725e7816f27`) | needs_revision | 明确不匹配40管/6板 | 正确事实检出与材料性判断；P2-O03要求额外补未引用项的修复范围越界。 |
| corrected / broad (`fb42eb2d7e0b`) | needs_revision | 未提及 | F02及现场N01有据检出；26 m条款归类和专家评审已完成的说法须作上述限定；Correctness仍过宽。 |

### 完整实际输入与参数核验

最后一格实际1请求/1响应，system与同一冻结system逐字相同，human132,533字符、SHA`3ed124b3968590a6d86c08ec7160127d43dc2f25ac3cc6de89d978c6373af356`匹配当前冻结；完整source和corrected正文都实际到达。四格独立核对actual user/system均通过，四个diagnostic回调参数完全相同，实际唯一schema工具仍为GraderResponse，无检索/导出/执行工具。四格共4响应、327,780 total_tokens；不重复累加其中reasoning_tokens。

结束后独立核查freeze中的36文件hash仍全匹配，source/candidate/system与调用前记录相同。没有作者调用或新报告；两个数量版本是调用前构造的测试输入，不是模型发现后完成的修复。本文没有调用模型、改变材料或把评审意见注入任何运行。

### 混合结果及后续设计证据

本组支持的窄结论是：**在当前DeepSeek、当前calibrated system、同一完整报告和自动compact证据包下，明确局部责任的正负数量判别均正确；两个全稿输出均未明确处理该数量目标。** 自动表格至少在本次局部任务中可被正确解释，不能再把它描述成模型必然无法理解、或必须手工补列才可判断。

同时全稿corrected格发现了真实F02/N01，original格却全通过；不能说“broad总是失败”，也不能推断单处把40改6导致范围/活动问题才出现。每条件仅一次、样本为已反复使用的开发题，scope还改变了显著位置提示和判定任务；不足以证明普遍因果或稳定可靠性。两个local输出也分别有P3理由瑕疵和P2修复范围越界，故不能把目标2/2命中升格为可靠交付链。

这些观察为“让公开判断明确对应受托主张、实际证据和适用结论范围”的输出契约原型提供设计依据：本次问题横跨漏判、过宽通过、出处错归与越界修复，不能只要求更长解释或固定逐项专家流程。该原型是否改善仍需独立验证，不因设计方向合理就先宣布成功。保留本组全部混合结果，不原样重跑已知样本直到有利；未来若主干应用新契约，仍须检查有据反馈能否转成正确保存稿及准确复评。

P2-O01/O03限制可靠接受/完整修订反馈的宣传及直接工程依赖；P3-O02限制额外论据复用，I01已被统一能力说明控制。隔离开发与明确受限稿可继续，不新增运行时审批环节，不把发现自动变成停工命令。
