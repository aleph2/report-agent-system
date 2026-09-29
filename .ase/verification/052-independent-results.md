# Task052：格式形状与思考档位的分阶段独立评价

2026-09-30。评审者 `/root/llm_rl_expert`，只写本文件；不调用模型、不读写密钥/.env/私有reasoning，不改生产或他人文件。本记录先声明设计，后核实际输入并追加终态；不根据结果改oracle，不宣称flat已修复问题。

## 设计意见（结果前）

最多四次的方案足以形成此次有边界观察，无需扩展：阶段A为旧union/high/131072与flat/high/131072各一次；flat完整协议有效才阶段B，为flat/high/131072与flat/max/131072各一次。材料、system/user及六标准不变，原042 oracle不变。A比较wire形状，B固定容量后比较effort；分阶段报告，不把A、B的两个flat-high与一个max事后混算胜率。

阶段B门槛必须包括**原GraderResponse本地校验、status/passed/overall一致及精确六ID**，而非仅JSON可解析或flat形状通过。已读`acceptance_review.py`的`consistent_outcomes`：原规则继续约束每项passed与status、整体result与所有状态；不能因wire将passed改为boolean而降低本地判据。schema/协议失败保留且不补样本；API/运输失败依原证据诊断，未派发项另列，不能算能力失败。

flat保留原字段和说明，gap对所有项必填、通过项可空，属于格式候选。即使A表现不同，也可能有采样及表示形状影响，不能由一次union失败/flat成功识别union为唯一根因；B仅一次每设置也不证明稳定effort效果。与051 high比较还改变了上限，最多观察此次是否再次截断，不能由一次未截断估计容量修复率。

SDK MockTransport与线上request hook有明确用途：核验实际序列化请求的URL路径、JSON/hash与冻结payload、strict字段是否匹配。它们**不证明服务端实际启用了约束解码或保证返回合规**。URL只记录安全scheme/host/path，不能留下headers、query、userinfo、密钥或reasoning。每份计划request、派发顺序和继续条件应先冻结，实际结果不得改变比较身份。

原始响应必须保留。flat通过项的`gap=""`若被原union本地解析器忽略，raw与model_dump的差异只能如实注明为既有校验的字段规范化；不能因此冒称字节相同，也不能手补缺gap、改ID或改status后当成功。所有语义字段仍逐项核对。

## 固定评分口径

沿用042 oracle：O1按现稿已采用“易滑软弱地层”分类，70与75～100存在确定条件矛盾；O2现有雨量及替代前提下100受支持；O3真实高度未知与确定分档缺乏证据分开。分别评价公开关系（正确/错误/未表达）、C2/overall裁决、正确和未知对照、误拒与有据修复，不建立其他五项完整gold。未表达不推断内部不懂，overall N不自动算识别O1。

协议有效不替代语义正确；公开正确但协议无效不计有效交付。修复分类须有源，不能靠改标签匹配70，不能猜高度或误降正确雨量。来源未提供给本次模型、已提供但未识别、源本身缺失须分开。新确认bug按P0–P3列明具体阻断动作和隔离方式；研究假说不报成bug。

## 实际准备与发送核验

已读Task052及实际运行器，并直接比较四份冻结request：所有messages逐字等于050，全部max_tokens=131072；A两份只差tools，B两份只差reasoning_effort，a-flat-high与b-flat-high完全相等。a-union-high相对050 high仅增加max_tokens，未另改角色或材料。四份文件hash与manifest匹配，所有frozen_files最终重算一致，042 oracle未变。

flat实际为原失败分支的字段全集（七字段含gap），全部required、additionalProperties=false；相对该分支仅passed变boolean、gap说明增加通过时空串要求。其他属性逐字段不变，保留ID enum与原证据/解释/所需结果字段。已读投影实现：先wire schema校验，再检查passed=true时gap必须精确为空串；只删除这些空字段并记录路径，随后原GraderResponse本地一致性及精确ID校验，额外未声明规范化会报错。没有修补缺字段、非空gap、ID或语义值的路径。运行器的B门槛同时检查A阶段终态、无API阶段错误/冻结变更、A-flat完成全链协议校验，未按语义结果筛选。

A两份`outgoing.json`均记录POST对应的安全URL为`https://api.deepseek.com/beta/chat/completions`、correct_url=true、json_equals_frozen=true、strict_flags=[true]。已读hook实现，其直接比较SDK实际body JSON与冻结对象，禁止不符目标、query或userinfo；不导出headers/密钥。union/flat实际body SHA分别为`ac0211624b3eeccdf4ff21cc667f19386a4e2f26fd6fdbe5c4b861c4da30bcc3`、`d706499cc518a887cca1d5adbc5b0e9679dd17181e22e281b263a043a65daed7`。body字节hash与美化保存的request文件hash不同不构成JSON不一致。该观察确认了SDK请求边界的序列化与strict发送意图，不证明服务端约束执行。

Main报告12项离线测试及alignment实际核查通过；本评审没有重跑它们，也不将其替代线上输出。准备核验未称flat成功，后续终态如下；未追加调用。

## 终态：A调用超时，B未派发

**本轮没有获得可评分的在线回答。** 独立读取最终manifest、两个A receipt及outgoing，再核四份request和全部冻结文件hash，均与准备记录一致。实际状态：

| 计划样本 | 调用与终态 | 可评分范围 |
| --- | --- | --- |
| a-union-high | 1请求、0完整response；API阶段APITimeoutError，cause_types为ReadTimeout/ReadTimeout；约1928.1秒，retry0、usage null、postflight true | 没有response/output/wire-output，协议合规性与O1/O2/O3、裁决和修复均不可评分 |
| a-flat-high | 1请求、0完整response；同样API阶段APITimeoutError及ReadTimeout；约1928.0秒，retry0、usage null、postflight true | 没有response/output/wire-output，未进入投影或完整flat协议校验，不能判flat成功或失败 |
| b-flat-high | **未派发**；仅有冻结request，无outgoing/receipt/response/output/wire-output | 不计为模型失败或完成的effort样本 |
| b-flat-max | **未派发**；仅有冻结request，无outgoing/receipt/response/output/wire-output | 不计为模型失败或完成的effort样本 |

manifest明确stage A=`completed`（尝试已终态，不代表模型成功），stage B=`not_run`，reason为A均超时、完整flat协议门槛未满足。两个A的请求hash均与receipt/manifest匹配；安全hook仍记录正确URL、JSON等于冻结请求及strict=true。SDK发送边界已有证据，服务端是否执行strict仍未知；没有完整返回可供比较union与flat。

**P2-052-R01：两次API读取超时使本轮在线对照无法交付结果，根因未定。** 阻断这次A的在线格式效果评价、按预声明启动B及effort效果评价，也阻断由本轮声称flat已在线修复、模型质量通过/不通过或G1完成。原始attempt、hook、错误receipt和B未派发状态足以隔离；不阻断保存/提交候选代码及离线、实验记录，不要求撤销已有离线核验。Main负责整合及后续处置，本次不自动重试、修复响应或补样本。

本地超时不能说明远端已取消、生成完成、排队失败或计费为零；两条usage均缺失，**未知不记零**。相近耗时、发送hook及本地连接观察也不足区分生成、排队或链路原因。receipt的read timeout为1800秒；约1928秒总耗时不直接证明该参数失效，因为未配置整体执行deadline。未读取任何私有推理来填补这些未知。

本轮实际获得的是请求与strict参数在SDK发送边界匹配的证据，以及两个明确保留的调用超时；**在线对照被调用超时阻断，而非模型语义质量验证不通过。** B条件未满足且未派发符合预声明。四份预备请求不等于四次调用，本次仅两次、零重试；052独立核验至此完成，没有额外调用、邮件或生产变更。
