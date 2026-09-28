# Task025 H1 合成hold-out独立内容评分

2026-09-29。独立标签设计/评审者：研发 reviewer 子代理 `postrun_review`。先核验5个已完成格，再按Main完成通知补核余下3格；现4案例×2臂全部8格完成独立评分。未轮询或评分运行中的原生真实项目。

输入与标签使用先前冻结版本。标签SHA256仍为 `e4978cc177cdd26771964c407cd4e08c7b69841d44ed6980a18161585b102be0`，未修改；未读隐藏reasoning、opaque checkpoint或凭据，无模型/网络调用。只读各已完成格的output/input/settings和脱敏普通tool观察，唯一写入本文。

## Findings first：主要判定正确，部分修订措辞仍有缺陷

**P2-025-H1-01：换算案例transcript允许把已可直接纠正的错误留作未决。** `4f86c2a09db1-transcript-0/output.json` 的Correctness正确要求352支，但Human authority的gap又允许“either correct the total or explicitly disclose the conflicting figures as unresolved”。原始两源一致、算术确定，没有需要人裁定的来源冲突；把报告自己写错的5.5留作未决不是已完成正确汇编的等价修复。这是附加反馈的修复边界缺陷，不推翻该格对H02-Q01的明确正确检出。影响：如果作者采用该替代项，可能仍留下可纠正错误。当前仅有评审输出、没有已发生的错误修订；隔离反馈、保留352的明确证据可以容纳本批诊断。阻断“此格已证明可靠修订反馈/纠错完成”的声明，不阻断主要判定记为命中，也不停止其他格或真实主干实验。Main负责后续真实修订验证，现未解决。

**P3-025-H1-02：扫描案例transcript增加未经证实的批准状态。** `a9c17d5e8034-transcript-0/output.json` Human authority gap要求7/3、7/5标为“unapproved/unexecuted plans”。r21/r22证明尚未执行和日期为计划；没有提供最终批准人的姓名不证明计划未经批准。`unexecuted`有据，`unapproved`是额外状态推断。该局部措辞不改变H03-C01正确检出，但不应写回合成报告为新事实。去除无依据形容词即可控制；不阻断本格判定或批次继续，不新增人类批准要求。Main记录，待后续反馈/作者行为验证。

二者均应与顶层判定质量分开，而非把有附加缺陷的输出简单计为完全无误，也不夸大为模型未检出主要问题。没有确认其他应阻断当前隔离评分的缺陷。继续已授权批次能提供有用比较；为这些局部反馈先停整批或反复重跑当前格会增加延迟，不能替代之后的真实作者修订证据。

## 已完成格的独立内容评分

| Case/arm | 预声明判定 | 实际判定 | 支持关系与内容评分 |
| --- | --- | --- | --- |
| b3e72a91c640 / transcript-0 | satisfied | satisfied | 明确24/15/9、36+150−138=48、21参加人次；区分在借与逾期、签到与独立人数，保留标识未安装。有据接受，无新增实质误指控。 |
| b3e72a91c640 / artifact-0 | satisfied | satisfied | 明确三类余额与合计48、活动人次和待办与r01–r03一致。有据接受，无新增实质误指控。 |
| 4f86c2a09db1 / transcript-0 | needs_revision | needs_revision | 明确§二/四的44÷8=5.5与r11/r12的8支/盒及112+168+72不一致，给出44×8=352。H02-Q01正确检出；P2-025-H1-01另记。 |
| 4f86c2a09db1 / artifact-0 | needs_revision | needs_revision | 指明同一错误及两个重复位置、r11，明确修正352并保持摘要/表一致。H02-Q01正确检出，无新增实质误指控。 |
| a9c17d5e8034 / transcript-0 | needs_revision | needs_revision | 明确§二声称已扫描/QC与r21日志p1记录B及§三/四相冲突，要求仅清点编号完成、扫描/QC待做。H03-C01正确检出；P3-025-H1-02另记。 |
| a9c17d5e8034 / artifact-0 | needs_revision | needs_revision | 明确§二完成断言与r21记录B、§三相反，要求撤回无据完成声明、对齐截止日实际状态。H03-C01正确检出，未加“未经批准”的无依据状态。 |
| 6d02fb83a157 / transcript-0 | satisfied | satisfied | 明确并列两套来访统计、记录出处、可采用结论边界，不裁定哪个来源正确；确认差值23及活动29人次。有据受限接受，没有因尚未对账而误拒。 |
| 6d02fb83a157 / artifact-0 | satisfied | satisfied | 明确两套来源与23差值保持未决、结论边界及来源r31–r33；未强制选值、补查或平均为最终量。有据受限接受。 |

以上不是只匹配result。所有负例均公开给出具体错句、来源/段落和所需正确状态，所有正例明确确认关键数据与边界。不要求固定工具顺序或为通过例额外编造问题。测试输入明定无需导出/版式，模型提到export并非必交条件；本harness确实提供了生成导出且各格实际读取，因此这里不因“导出存在”措辞额外判错，也不将其视为视觉验收。

## 真实可见证据核对

- 每格实际首请求system/human分别精确等于其input.json内容；五格settings.parameters相等，工具目录相同（包含read_review_context），grounded_verdict=false。H1差别为input_mode，system/rubric/schema不据输出措辞变化认定改变。实际初始消息长度/排列不同是输入组织实验的一部分，不是假定相同上下文长度。
- 五格实际read_source_page普通返回，逐来源内容拼接均与对应冻结source.content**逐字相等**：借阅r01/r02/r03、换算r11/r12、扫描r21/r22。它们实际出现在后续模型请求中，不仅有调用起点。
- 借阅两臂导出读取并集各覆盖全部61块；换算两臂各53块；扫描transcript一次覆盖29块。因此所评分的实质错句/前后文及正确内容可见，不是依据未取到的资料要求模型猜测。借阅artifact还通过read_result取得与冻结正文完全相等的body。
- 初始transcript消息包含作者完成陈述，artifact初始没有，但可通过共同工具获取。实测：借阅artifact调用read_review_context的assignment/history/state；借阅transcript读history/assignment；换算artifact读history；换算transcript读assignment；扫描transcript读assignment/state。**不能把artifact理解为永久剥夺作者历史，也不能假称每个格都读取相同context段。**
- 借阅/换算格使用calculate是各自选择。其返回与公开算术理由一致；扫描格不需要算术工具也能正确判断状态矛盾。此处记录行为，不把这些工具链规定为验收流程。

补核余下三格：其首请求system/human与各input.json逐字相等，settings.parameters/system_sha256/rubric_sha256/工具目录均与前5格基准相等。扫描artifact收到r21/r22完整原文和全部29个导出块，另读read_review_context.assignment；来源冲突transcript收到r31/r32/r33完整原文、全部42个导出块，另读assignment；来源冲突artifact也收到三源、42个导出块，并read_result取得与冻结正文逐字相等的body，没有调用read_review_context。没有调用某个可选工具不影响已足够的证据链。

来源冲突transcript理由列出平均数883.5的算术正确性，同时明确不裁定来源差异；原稿本来就说不采用这个平均数，因此不能把提到算术结果误判为要求采用它。artifact理由将差值简称“23-person difference”，建议保留“23人次”的准确单位以免误读；当前未明确声称是23名不同访客，也未以此选择总量，不认定新增实质误指控。两格都没有把未对账变成必须拒绝的通用规则。

完整结果为：**两臂各4/4主要判定有据；共4次受限/有效接受、4次实质缺陷检出，没有对两个预声明可接受案例的误拒。** 这不是8份不同报告的独立准确率，也不是所有反馈都无缺陷；P2-025-H1-01与P3-025-H1-02继续单列。它们是约1300字的明确合成事务材料，与复杂真实工程报告难度和上下文不同；主要判定命中没有替代真实自主选证/反馈/作者修订/再审闭环。

## 完整批次处置与证据限度

两臂在四个已配对案例上的主要判定完全相同；没有证据宣称artifact在这个样本集提高总体识别率或降低误拒。两臂均成功也不能推导H1毫无作用或在更复杂任务必然无效。差别包括自主工具访问与附加反馈措辞：目前记录的两项局部反馈问题出现在transcript臂，单次/格不足以将其因果归给输入模式或宣称artifact稳定更好。

独立再次核对冻结文件：输入SHA256仍为 `c398b88af2b174c82c62c6fd7b0d481176c7d492f06483c2b627176fe633605a`，标签仍为页首hash，没有根据结果调整样本或标准。Main负责批次完整性/费用/全量代码冻结审计；本review的重要内容判断以实际公开I/O为准，未独立重验Main全部冻结记录。

H1合成批次评分完成，允许如实交付该8格结果并继续已授权真实主干验证；P2/P3不自动停止其他实验，但尚不能声称反馈后的真实作者修复正确。真实项目在途运行不在本次评分内，待完成后另按其保存结果、来源和变更核验。本review不补人工答案进模型、不干预运行，不因合成全部主要判定成功而质量晋升或新增运行时审核关卡。
