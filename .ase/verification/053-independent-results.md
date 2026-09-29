# Task053 独立核验：用户授权重放052的两项A请求

状态：两次请求均终态，独立公开输出复核完成；B未计划、未派发。2026-09-30。执行角色：LLM/RL specialist；只读既有任务、冻结请求、安全发出记录及公开结果，只写本文件。未读取 `.env`、私有推理或 checkpoint，未调用模型、修改生产或追加试验。

## 重放边界与输入核验

用户要求052超时后“再试一次”。本轮仅 `.runs/task053/flat-retry` 的 `a-union-high`、`a-flat-high` 各一次，继承052的 high / 131072、官方 `/beta`、thinking、strict、SDK retries=0 及 read timeout=1800；无 B 自动派发。复用052已完成的设计/离线验证，不将两次超时改写为模型质量失败。

独立读取053任务和本地 launcher，并重算 manifest 受保护文件 hash：全部匹配，包括 runner、模型/验证定义、原冻结请求和042 oracle。两份053请求与各自052请求逐字节相同；两种 shape 的既有差异未扩大。

| 请求 | 冻结文件 SHA256 | 与052对应请求 |
|---|---|---|
| a-union-high | `d8f39387da7daf9dbb8f924121a0332f66fa8eecf850774a099baab7ab2739cd` | 字节、JSON均相同 |
| a-flat-high | `a5064f20b939798322d61b0a28f30912a3502a6cbfa01bea613df62b6e726717` | 字节、JSON均相同 |

两份 `outgoing.json` 都为 `https://api.deepseek.com/beta/chat/completions`，`correct_url=true`、`json_equals_frozen=true`、`strict_flags=[true]`。实际 SDK body hash 分别为 `ac0211624b3eeccdf4ff21cc667f19386a4e2f26fd6fdbe5c4b861c4da30bcc3`、`d706499cc518a887cca1d5adbc5b0e9679dd17181e22e281b263a043a65daed7`，与052一致。它们验证本地序列化发出边界，不证明服务器实际执行 strict 约束。

manifest 沿用052四项计划模板，但明确 `authorized_requests=2`、`replay_scope=Only stage A`、`stages.b=not_planned`；launcher 只复制 stage A 请求并调用 A。独立核查未见 B 运行工件。不能把继承模板读成此次已发四请求。

冻结042 oracle SHA256仍为 `f09f6e5acaf08a3db2e96784e8f7dabf522397d2ef3c9a653f54b35215f4a3c7`。没有新源证据，不改变 O1 条件矛盾、O2 条件支持、O3 高度未知边界；其余五项没有全量 gold。

## 已到达公开结果

| 样本 | 调用/协议 | O1关系 → C2裁决 | O2 | O3 | 总体结果 |
|---|---|---|---|---|---|
| a-flat-high | 1 request / 1 response；协议有效，精确六ID；公开JSON与wire一致 | 正确表达70不在已采用类别75–100内，继而以披露/等级不变豁免，错误判 S | 正确表达缺五年资料时当地年雨量替代及>1000→100的条件支持 | 承认原表高度空白、现有档位是假定，未建立真实高度 | 六项 S / satisfied；错误放行 |
| a-union-high | 1 request / 1 response；协议有效，精确六ID；raw arguments与output一致 | 正确表达70不在75–100内，C2 N，不以披露/等级不变豁免 | 正确表达条件支持 | 承认高度空白/假设，却在C2 explanation称该取值“有据”；真实高度仍未解决 | C2 N、其余五项S / needs_revision；关键拒绝正确，但非全答正确 |

flat 的 `finish_reason=tool_calls`，返回一次 `GraderResponse`；raw function arguments 解析值等于 `wire-output.json`。独立复算 canonical projection 只删除 `criteria/0..5/gap` 六个通过项的空字符串，结果等于 `output.json`；未删除非空内容或修补模型原文。六个 name 与请求 enum 逐项相同，passed/status/overall一致。协议有效不等于标准判断正确。

flat 返回 model=`deepseek-flash`，fingerprint=`aeb56401ca74e127821c4f9126dcb669`；约151.2秒。usage：prompt 135884、completion 40416、total 176300；reasoning_tokens 36630 是 completion 子集，仅使用计数。一次返回不证明服务普遍恢复、flat稳定可靠或 shape 带来效果。

union 同样返回一次 `GraderResponse`、`finish_reason=tool_calls`，raw arguments解析值等于output，未作canonical projection；六ID有效，C2的false/not_satisfied有gap，overall为needs_revision。约282.1秒；prompt 136351、completion 76148、total 212499，reasoning_tokens 72951为completion子集。两次都返回deepseek-flash及同一fingerprint，但相同后端标识不能排除抽样变异。两次合计prompt 272235、completion 116564、total 388799，不将reasoning计数重复相加。

## flat 的语义裁决与修复

O1 在 C2 evidence 和 explanation 均明确读出：①自述“易滑软弱地层”，指南该类别75–100、全风化层50–74，而70落在后者；这是公开正确识别后裁决豁免，不再只是未表达关系。C2却以两处判断值已披露且不改变风险等级为由称其不违背标准，`needed_outcome`为“No change needed”。原标准没有这一豁免。既有条件矛盾足以要求 C2 N / overall needs_revision，无需先证明真实地层分类，也不需证明总等级变化。

O2明确引用指南 p.20 的替代条件及“超过1000mm，分值为100”，与现稿1304.4–1582.5mm和R31=100相符。它是正确内容的条件支持，不能替整项C2通过；也不证明整个资料库没有五年雨量记录。

O3承认①设计高度留空，并称20≤H<30和X11=40为假定，没有给出新的高度源依据。这准确保留了一部分未知边界，却未支持报告当前确定档位。C6同时称核心坡高/岩性等均与来源一致，并把缺证描述当“coverage limitations, not established misstatements”：无已证反例不足以建立该范围的肯定结论。p.96“可塑或其下硬塑”不能仅凭字面就判坡体“局部软塑”事实错误；本记录只认缺证/过宽肯定，不宣称新增岩性冲突 gold。

本输出没有拒绝正确R31，也未编造替代高度，未观察到拒绝型假阳性。修复不足：仅建议确认后收紧表述/协调岩性高度，未要求解决已明确建立的O1条件矛盾。合格修复可以是按当前有据类别选取合规值并重算，或用独立来源支持不同分类后重新选档；不能仅改标签使70合法。无需指定75为唯一值。

## union 的语义裁决与修复

union准确连接报告分类、指南两档和70的位置，明确据此判C2 N，overall needs_revision；已达到本固定样本的关键关系—裁决目标。它保留正确R31，没有要求无依据改动雨量；也没有编造①高度。其余五项S没有全量gold，不记为六项全部正确。

两个范围问题仍成立。第一，C2已写设计高度为空、20≤H<30是假设，explanation却将①X11与R31并列为“有据”，没有新增证据支撑真实高度或所选档位。第二，C2和总体理由把基础持力层“可塑或其下硬塑”与坡体“局部软塑”说成已确立不符；所读材料只足以确认对应依据未见，不能排除不同空间/层位。其C6又承认括注可能来自本次未提供的地勘，把该问题并入C2后判S。因此关键O1拒绝有独立充分依据，但附加的岩性冲突说法是过强指控，属于局部假阳性；不把总体needs_revision改判为误拒。

修复方向有用但限定不足：gap要求按该类取“≥75”或改判分类，并落实“局部软塑”来源/否则删除；needed_outcome还要求数值变化时重算F。全文已有75–100，不能仅凭gap省略100就认定它建议超过100；不过面向作者的约束宜完整保留区间。另一条“将材料改判为相应档位”未明确要求分类本身由独立来源支持，邻近对括注的来源要求也不能直接授权改分类。执行前应保留“有源分类→对应档位→重算”的条件，避免为了保留70而只改文字。本次未执行修复，不能声称已造成报告损坏。

## 本次已确认问题与阻断范围

| 编号 | 级别与理由 | 具体阻断动作 | 隔离与处置 |
|---|---|---|---|
| P2-053-R01 | flat 公开正确识别 O1 后以未获标准授权的披露/等级不变理由判 C2 S，进而全项S | 阻断用该裁决宣布报告满足全部六标准、自动免修复或工程签发；不阻断保存结果或完成这对诊断 | 保留原始输出，独立反馈保留C2 N和有源修复要求；本轮不追加调用 |
| P2-053-R02 | flat C6已承认部分岩性/高度缺证，仍作覆盖这些数据的肯定一致结论 | 阻断把C6 S当成这些事实已经独立验证的依据；不阻断以明确未知交付阶段性草稿 | 对相关数据维持缺证/未知；不伪造冲突或全六项gold，不把未知一律转成错误 |
| P2-053-R03 | union将①高度假定称“有据”，并把未见坡体软塑来源夸成与基础持力层原文已证冲突；C6仍过宽肯定 | 阻断将这些附加断言作为直接改写高度/岩性、免于查源或确认C6全面合规的依据；不阻断基于独立O1矛盾要求修订 | 保留正确C2 N；撤去缺证即冲突/假定即有据的推断，相关事实维持未知，作者修复必须有源且服从完整档位 |

## 终态与可作结论

最终manifest `stages.a=completed`、`stages.b=not_planned`，仅两项A results且均completed。两份receipt各1 request/1 response、max_retries=0、postflight_matches=true；独立终态重算受保护hash全匹配，请求仍与052逐字节一致；未见B请求/receipt/response等运行工件。没有追加样本。052的两条超时原记录保留，不能用本轮返回反推先前超时原因或远端计费。

本轮协议交付两项都有效；O1公开正确关系两项都有，正确C2 N仅union一项。两项均有未知事实与肯定结论范围问题，故“有效关键拒绝”不等于“完整审核正确”。这是一对各一次的固定样本，不能归因于union/flat、估计稳定收益或宣布flat修复失败；也不以耗时作性能比较。当前证据只支持分别保留协议结果与语义结果，flat尚不能凭本轮晋升为可靠审核方案。B不在本轮授权执行范围，flat有效不触发B。本记录没有新增模型或生产动作建议。
