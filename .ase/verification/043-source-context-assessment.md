# Task043：源观察结构与最小上下文候选

2026-09-29，研发 worker/context-curator `/root/review_fork`，Main 分配的只读实现定位。
本文创建前目标文件不存在。只读取当前实现、027既有记录和040公开JSON；仅写本文。
未改 runtime、源文件、042冻结文件/旧输入，未打开真实state.db或checkpoint，未重新提取
PDF/OCR、查询新资料、读取凭据、调用模型。Main另行负责native入口及实验设计。

**建议的最小新候选是仅改变搜索结果的自动附表方式：完整命中文本与分页不动，缺省提供
明确标记的逐页引用，agent可选择旧完整附表或直接inspect任意页。** 当前已有的compact
geometry应复用而非重造，但027的失败不能被遗忘；它不是这次按需访问候选的效果证据。
以下字符数证明观察结构和体积，不证明042/040失败由长度、位置、截断或注意力造成。

## 1. 实际观察及统计口径

输入是`.analysis/task040/action-observations.json`中sequence≥353、tool属于
`read_source_page / inspect_source_page / search_sources`、状态success的15条grader观察。
该文件SHA256为`7d590b12a78cec3774662f08c9c5186d428c146b7efb116c6c7b554cadcfaceb`。
本次重新逐条核对各`received_in_request`的公开tool消息：原字符串SHA及解码JSON均匹配；
审计文件`.analysis/task040/actual/model-io.json`的SHA256为
`462b995bf00b14f4b23e48a0fe583a575c6cc9265d4ccc22647c3dd2d2697fa5`。

15条实际callback content共**228,004个Unicode字符**。下表JSON字段大小用
`len(json.dumps(value, ensure_ascii=False))`计算；与实际整条观察长度一致。它不是token数、
文件UTF-8字节数或整次请求大小。042把来源审计信封也内联后的233,636字符是另一口径。

| seq / 工具 | 整条字符 | 返回块/命中数 | 块/命中数组JSON | table字段JSON | 表格rows JSON | 非空cell bounds JSON |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
|416 inspect p20|3,886|1|1,064|1,280|0|0|
|420 inspect p21|4,018|1|1,144|1,280|0|0|
|424 inspect p22|3,800|1|1,031|1,280|0|0|
|428 inspect p23|3,453|1|851|1,280|0|0|
|432 search 表3-3|552|0|2|2|0|0|
|436 search 风险等级|24,449|10|11,084|12,818|0|0|
|440 search 2n|7,786|3|3,390|3,848|0|0|
|444 search 表5-2|552|0|2|2|0|0|
|448 search 5-2|2,962|1|1,132|1,282|0|0|
|456 search 深挖路堑|93,395|10|25,152|67,694|20,661|32,296|
|460 search 1582.5|5,189|1|2,218|2,423|97|922|
|464 read 编写范围说明|2,214|1|728|2|0|0|
|496 inspect p19|3,904|1|1,089|1,280|0|0|
|500 inspect p18|4,052|1|1,150|1,280|0|0|
|504 search K1319+910|67,792|5|8,970|57,990|14,764|35,933|
|合计|228,004|37|59,007|153,741|35,522|69,151|

table字段指search/read的`source_table_views`数组或inspect的`table_view`对象，含空数组。
rows/bounds是table字段内部的嵌套子集，**不能把这些列再相加**。inspect还有单独native_text。

- 两个最大search共161,187字符，占这15条70.7%；其table字段合计125,684字符，占两条78.0%。
- 全部table字段占67.43%；仅`nonempty_cell_bounds`就占全部30.33%，表格rows占15.58%。
  40,501字符的JSON块文本和3,992字符的JSON native_text分别占17.76%、1.75%。
- 共36次页表视图、34个不同source/page；23个表候选、206行、3,206个矩阵位置。
  040这些表没有`geometry`字段，使用旧raw bounds；不是027 compact已经启用的输出。
- 21次视图为`no_tables_detected`，15次为`extracted`。无表视图共26,918字符，占11.81%。
  全部视图重复携带的limitations数组共23,364字符、extractor对象共5,652字符；这些也是
  嵌套统计，不可与table总量相加。没有检测到线表，仍不代表页面没有规则或可用表格内容。

### 哪些重复已经证明，哪些不能当重复删掉

1. **跨调用完全相同的页表补充。** 设计source `07fe4d16-e482-4ee5-83ac-5dd2cdc1bdb6`
   的物理p95与p96在seq456、504各返回一次。其完整view分别20,128、9,873字符；二次拷贝
   共30,001字符，占所有15条13.16%。同两页的原冻结块ordinal94/95也逐字重复，原文本
   共2,361字符。37个返回块中有35种不同text字符串。这是可核验的重复，不是语义相似猜测。
2. **同页不同表示，不一定逐字重复。** inspect同时返回新读PDF的native_text、冻结抽取块
   与几何表。六页native_text共3,578原字符，冻结块4,025原字符；六对均不满足原串包含，
   简单统一CRLF后也不满足。不能把冻结OCR或native_text随意删成“完全重复”。
3. **同页几何候选包含关系，不等于可删除的重复表。** p99、107、113、119、126、134有
   大bbox包含小bbox的候选，rows并不相等。022已经记录图框/套表候选问题；机械检测不提供
   语义表格身份，不能一律删嵌套候选，也不能把23候选称23张有效业务表。
4. 页视图在**单次返回内**已经按source/page去重；重复主要跨独立查询重新发生。不能再以
   “加单次去重”作为新功能。跨调用自动省略则需保留可重取能力和可见声明，不能隐式假定
   agent仍记得此前内容；它不是本次推荐的首个实现。

## 2. 具体生成路径与当前agent能力

| 代码位置 | 已有行为与限制 |
| --- | --- |
|[catalog.py:35](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/catalog.py:35)|`_blocks`把来源块机械切成最多4,000字符；所有字符保留。块边界不是语义页/段落。|
|[catalog.py:85](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/catalog.py:85)|`read(source_id,offset,limit)`按冻结块读，limit为1–50，带ordinal/locator/total_blocks/next_offset。工具名read_source_page不表示参数是物理PDF页。可按已知ID读取历史版本。|
|[catalog.py:103](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/catalog.py:103)|`search`是ASCII不区分大小写的literal substring；可按source_id限定，默认当前来源。返回完整命中起始块，跨块命中保留续块；按来源/块顺序而非相关性排名分页。offset/limit数命中块组，不限制表格字数。|
|[deep_runtime.py:216](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/deep_runtime.py:216)|read与search包装器无条件调用`with_source_tables`。search参数只有query/offset/limit/source_id；目前没有agent可选字段投影或关闭附表参数。|
|[source_tables.py:153](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/source_tables.py:153)|从返回块的明确locators识别物理页，按source/page去重，然后为所有这些页补表。无法定位的项另列`table_view_unlocated`。不把ordinal猜成页码。|
|[source_tables.py:79](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/source_tables.py:79)|`source_tables`对选中页做pdfplumber线几何表检测；默认每表返回全部rows、bbox、每个非空cell的row/column/bbox。页级来源hash、版本/settings、limitations重复附在每页。整页补充可超出当前命中块/查询词；没有对表格的分页或field选择。8MiB内容流保护是解码限制，不是模型字符预算。|
|[document_tools.py:166](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/document_tools.py:166)|`source_page_info`支撑inspect_source_page(source_id,page)：1基物理页，返回native_text、raw table_view、按显式locator找到的冻结块、image_ref和限制。无字段选择/表格行分页。image_ref不等于模型看到了图片。|
|[document_tools.py:58](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/document_tools.py:58)|读取原件仍由server绑定workspace；只接受项目source_id，原件路径限制在该项目sources下并核SHA。PDF格式和物理页范围也校验。候选不得增加路径/URL或跨项目访问入口。|
|[deep_runtime.py:322](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/deep_runtime.py:322)|验收agent另有`analyze_evidence`：自主提出问题、选择source块范围和result字符范围，单次局部LLM分析；不是新的agent/必须阶段。其[source selection](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/evidence_analysis.py:54)也附whole-page表，所以本身不是细粒度表格投影。另有可选analyze_text及按页/crop的analyze_source_image，本次未调用。|

040实际使用了自主范围选择：seq456对设计source定向查询10命中，next_offset为空；seq504
未限定source，先返回33组中的5组，next_offset=5；seq436是22组中的前10组，next_offset=10。
这些游标已经能让agent继续、改词、缩小来源/limit或按页深入，不应再编写固定查页顺序。
但是limit=1也可能附该命中页的整张大表；`next_offset`仅描述文本检索页，**不分页附表**。

上下文管理还需区分父agent与grader：[deep_runtime.py:568](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/deep_runtime.py:568)
给native grader传入只读工具、TodoListMiddleware和BusinessBoundary；
[review.py:31](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/review.py:31)
用`create_agent`构建grader。父coordinator的FilesystemMiddleware/StateBackend不是自动传给
grader的源结果卸载机制。当前配置未给grader增加源结果字段投影/文件式按需读取；已有
read_review_context分页读取捕获的assignment/state/history，也不是新grader源工具返回的
自动压缩器。无需另造完整上下文管理服务来解决本次search包装器问题。

## 3. 必须复用的027能力和负面结果

[source_tables.py:25](C:/Users/dongy/Documents/ChatGPT/report-agent-system/src/report_agent/source_tables.py:25)
已有`_compact_table`：保留所有rows、空串/null，完整cell矩形通过共享x/y边和
`[row,column,row_span,column_span]`精确表达；不能无歧义转换时保留该表raw fallback。
仅normal read/search的附表按实验开关启用，inspect继续保留旧raw访问。它减少几何重复并
显式表示空cell结构，不是删去表义或改OCR，也不是agent自行选择的view参数。

[027验证记录](C:/Users/dongy/Documents/ChatGPT/report-agent-system/.ase/verification/027-compact-table-observations.md)
已经做过同页184,137→108,373字符（约41%缩小）的机械比较和一次native运行。该次实际
终请求341,915字符，最大search109,910字符，仍全通过、无作者修订；重要矛盾未解决。
因此不能把“再开启compact”描述成未试过的根因解决方案，更不能声称压缩必然改善审核。
这次引用既有记录，未重复运行027或重新抽取原页。

当前`review_context_experiment`的配置校验要求compact→calibrated_acceptance→
artifact+grounded，binder另要求017式新pre-review fork；不是任意fresh native项目的通用
source-view配置。requirement_acceptance路径的`reviewer_prompt`会直接返回新验收角色，
并不把旧grounded/calibration段落拼上，但旧配置依赖、绑定/身份条件仍在，不能靠开启一串
旧flag来伪装“只改search结果”。Main负责其余native入口设计，本文不另行扩展。

## 4. 最小候选：只改search的显式按需附表

建议第一次实现保持`read_source_page`、`inspect_source_page`、Catalog搜索逻辑、排序、
matches.text/locators/ordinals、total/offset/next_offset、原始来源与解析结果全部不动。
仅让`search_sources`支持例如`table_detail="references" | "full"`；缺省由该项目的可信
配置决定，显式full走原`with_source_tables`完整分支。agent始终可以直接inspect任意已知页，
也可以先选full，无“必须先搜再读再核”的隐藏业务流程。

references视图应做到：

- 每个明确定位的source/page保留source_id、来源hash、1基物理页和可调用的inspect参数；
  无法定位的来源仍显式列出，不猜页码。现有源ID/页码已足以调用inspect，不需新工具。
- 明确写“本次观察未请求/未附整页表格，细节可按页取得”，不能返回`no_tables_detected`或
  暗示原资料缺失/已被核查。若不再打开PDF做几何提取，不应声称这一轻量结果已核验原件
  当前字节；来源hash来自版本元数据，实际原件校验仍在full/inspect路径完成。
- 不做语义摘要、预选X21/R31或页19，不注入预期答案，不自动删嵌套表、空值或历史消息。
  来源引用是被明确省略视图的访问入口；不是把资料从系统中删掉，也不是字符阈值截尾。
- 全表按需取得后仍保留当前原始几何和限制。是否把existing compact作为另一个选项可以
  后续决定，不同时把compact、prompt、criteria、额外分析工具强制流程合成多个变量。

为估计数量级，离线仅对已保存JSON构造“原text检索字段+每页source_id/hash/page/inspect
参数+未附表声明”的示意投影：seq456从93,395变28,977字符；seq504从67,792变11,426。
**这不是已实现接口、正式性能承诺或经过模型验证的输入。** 增加完整具体来源元数据或
告知文字会改变长度；拿走自动显示的整页表格可能增加agent漏取表格的风险。
这项候选改变证据主动取得方式，不能把任何结果唯一归因为长度减少。

### 仅fresh诊断用新缺省，其余production保持旧缺省

最小边界是独立、版本化、server-bound的**source search视图配置**，而非复用旧验收提示词
实验链。由Main的fresh诊断准备器写入隔离workspace及准备收据，例如绑定
`version=search-table-view-v1 / default=references`；没有配置的项目继续full。
业务tool参数可用None作为“使用绑定缺省”的明确语义，显式full随时覆写本次显示选择。
agent只能选视图，不能修改项目绑定、角色、来源scope或原标准。

配置应加入诊断freeze与该次review target身份；仅在新项目/新诊断绑定时设定，已有绑定
恢复不得更换。未配置时不新增影响旧target的字段、不改旧checkpoint/裁决。此处所需是
可信准备入口的少量配置与校验，不是新的通用fork、缓存、服务或运行时审批框架。
不为了这项显示选择开启旧calibrated/claim-evidence flags；无需改原criteria/role prompt。

建议由Main在现有设计review中确定最后schema/绑定位置后再实现。相关机械检查可复用
`test_source_tables.py`的同页去重、跨页匹配、缺locator和hash/ownership案例，新增少量
“未配置/full与旧返回一致；references保留全部命中/游标并声明省略；按引用可取得完整
raw；配置不能在恢复时漂移”测试。native验证观察agent是否自主取得所需原页、是否仍
漏掉支持关系以及裁决范围是否与实际取得的证据相称，而不是只比较字符数。

## 5. 结论边界和实际交付

本次没有新增“体积导致错判”的已确认bug，也不把结构统计当因果结论。已有错误裁决仍
阻断全稿规则符合/G1/工程签发的声明；可追溯、隔离的研发候选不因这一质量问题自动停止。
本文完成的是代码定位、重复结构统计和候选边界，未实现新功能、调用付费模型或验证
自主取证/修稿改善。Main据此决定043设计与后续工作，独立alignment review仍在现有开发
review中进行，而不成为report运行阶段。

本次对应实现SHA256：

| 文件 | SHA256 |
| --- | --- |
| catalog.py | `195200e9da97bad325aa4634c884bcc26c68d647f676ddf26e7a9d5a04f7127c` |
| source_tables.py | `a2815900b25f9bf5dce6d7f991eff710f3e682be074995b8d379bdadd906b052` |
| document_tools.py | `2ceaad05db33b1624f428cb626666d34f62b4d1ad12164844e47439d06c88bab` |
| deep_runtime.py | `ff2bfd908fec665535c4351923f66cc1851098bc30fe43a96580afda5a984b52` |
| review.py | `89a210a8ad25d52cc778b2814e5807b7311e5d9815062287382567b9a0daf4f4` |
| review_context.py | `9727ee95c79e6dfdc8ea241aa04a56b1b0b237407ea2ca9daa9043ae5bb67970` |
