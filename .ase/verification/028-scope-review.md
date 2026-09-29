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
