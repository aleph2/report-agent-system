# 第0轮：覆盖基线、缺口与下一轮变更边界

Neo牵头测量设计和证据审核；Codex执行。目标是让重构前的实际覆盖可比较，而不是用测试数量证明系统正确。本轮仅增加诊断脚本和报告，不修改应用源码、现有测试、Prompt、依赖声明、原始资料、OCR、历史运行或预算账本。工作目录仍是Windows上的独立report-agent-system项目。

## 已确认的标准与当前口径

- 接口目标：当前有效公共接口、角色和合法配置，以及正常/非法/边界输入的契约义务全部有测试。注册、最终提供给模型、尝试调用、handler执行、结果和副作用断言是不同证据层。
- 路径目标：列明关键协议、状态转移及正常/拒绝/失败/恢复路径全部覆盖；循环覆盖0、1、边界和超界。不宣称所有可能路径组合覆盖。
- 条件目标：权限、所有权、版本、写入、预算、未知结果等关键判断的可行独立条件影响全部验证。普通受影响代码的分支目标为95%。分支覆盖不是MC/DC。
- 复用已有DeepAgents/LangChain运行图、Fake模型、HTTP MockTransport及真实临时持久化。覆盖不足通过补最少必要测试解决，不能依靠增加重复保护层或把错误预期改成通过。
- 测量结果是基线，不是合格线。程序处理正确不证明真实模型的选择、提示词遵循、报告事实、视觉排版或客户验收正确。

## 可复现范围

基准提交：`896c9975cac648e7cd5636e4ef6b38d5e71b459f`。使用现有WSL Python环境，直接访问同一个Windows项目目录，没有复制项目。coverage.py 7.16.2单独放在`/tmp/report-agent-round0-tools-20261018`，未改项目环境或依赖文件。

`measure.py`执行现有tests，采用全src/report_agent行/分支分母，保留旧接口测试、失败、跳过和收集错误。没有为提高数字筛除文件。旁观执行在相同测试上额外记录接口边界，逐nodeid与普通执行比较；即使结果一致，也不证明探针捕获所有adapter调用。

`inventory.py`在临时合成case中构建四种报告配置（managed context开/关 × knowledge开/关）及两种学习器配置（experiment capability开/关）。三个子角色通过正常delegated_task授权；Layout绑定合成快照；Reviewer声明合成审核材料。最终Fake模型bind_tools记录schema后由专用探针信号退出，不调用真实模型，不执行业务工具。该信号只终止测量，没有改应用控制循环。

独立接口探针初次直接调用子图缺少任务授权，另一次审核夹具缺材料声明；这些探针错误及修正均保留在raw目录的attempt1/2。最终探针不得用这两次失败宣称产品缺陷。

测量进程阻止TCP/UDP连接，保留MockTransport。该保护不覆盖子进程，也不是供应商用量审计。已核查显式测试子进程是临时CLI init；ReportExperiment测试使用已存缓存或拒绝unknown，没有执行付费子任务。Office本地渲染/能力检测另属子进程边界。没有启动真实报告模型验证。

## 实测结果

完整Python基线收集1868个唯一用例：**1726通过、112失败、21个setup错误、9个用例跳过**。另有2个模块在收集时因当前环境未安装可选GEPA/DSPy而跳过；pytest原摘要的11 skipped包含这两个模块。没有收集错误或已收集但未执行的用例。9个用例跳过源于未连接专用图数据库，本轮没有启用外部服务。

| 测量 | 实测 | 解释 |
|---|---:|---|
| 全应用93个Python源文件行覆盖 | 11066 / 12710 = **87.07%** | 未覆盖1644条语句；包含当前源码中的旧实现，不静默排除 |
| 全应用分支覆盖 | 4050 / 5048 = **80.23%** | 未覆盖998条分支弧；不是条件覆盖率 |
| 旁观执行与普通执行 | **1868项结果一致，差异0** | 两次都保留相同失败，不能解释成全绿或探针完整性证明 |
| 最终模型接口清点 | **18组角色×配置表面** | 4个报告配置×4角色，2个学习器配置×1角色 |
| 当前角色/工具名并集 | **173对** | 45对在旁观执行的BusinessBoundary入口出现过；这不是45/173的契约覆盖率。直接函数测试和optimizer不经这个入口；110条未归属BaseTool记录单列 |
| 关键协议路径 | **24族均有本轮通过的映射测试** | 每族只证明表中所列样例；尚不能给全部状态转移覆盖率 |
| 关键条件 | **清点18组，深入对照3组，3组均有缺口** | 其余15组及尚未清点的判断保持未知；全系统MC/DC未测定 |
| 已有前端VM测试 | **19/19通过** | Node覆盖报告只包含测试harness，不含VM中的app.js源码；不得报告前端应用100%覆盖 |
| Host接口声明 | **17个HTTP路由、11个CLI命令** | 源码声明单列；尚没有完整的接口义务/条件映射，不混入173个Agent角色/工具名对 |

普通执行约1150秒，旁观执行约932秒，二者有时间重叠，不把相加值当墙钟时间或LLM消耗。两个进程网络guard记录均为0次拒绝；本轮没有启动真实模型验证。普通执行前后源码hash一致；旁观执行期间只有独立`inventory.py`诊断脚本调整，应用src、既有tests、pyproject均未变。两个实际measure版本已分别保存，诊断脚本调整没有被隐瞒为“整个工作树字节不变”。旁观提前导入增加了anyio/langsmith两条pytest assertion-rewrite警告；精确用例结果一致，但不宣称执行环境所有细节一致。

机器结果入口：[metrics.json](metrics.json)；逐文件缺失行/分支：[file-coverage.csv](file-coverage.csv)、[file-coverage.json](file-coverage.json)；接口：[interface-matrix.json](interface-matrix.json)；完整最终schema见原始`.analysis/round0-coverage-20261018/interface-inventory.json`；路径及精确nodeid：[path-matrix.json](path-matrix.json)；全部失败、错误及跳过：[failures-and-skips.md](failures-and-skips.md)。

### 与本轮边界直接相关的模块

下表是命名模块视图，不另造“所有活跃代码”分母，完整93文件仍在CSV中。

| 模块 | 行覆盖 | 分支覆盖 |
|---|---:|---:|
| deep_runtime.py | 84.01% | 74.50% |
| task_context.py | 98.68% | 92.31% |
| decision_data.py | 94.51% | 88.39% |
| tool_transport.py | 95.56% | 90.91% |
| text_work.py | 94.31% | 86.31% |
| bounded_operations.py | 91.43% | 81.58% |
| artifact_review.py | 91.88% | 80.00% |
| working_summary.py | 100.00% | 91.67% |
| token_budget.py | 97.18% | 78.00% |
| learning.py | 93.01% | 75.93% |
| deepseek_strict.py | 90.85% | 78.57% |

working_summary行100%仍不能证明所有异常分类正确；token_budget单元覆盖很高仍不能证明普通用户入口绑定了它。这正是接口、路径、条件与结果断言需要分开检查的原因。

### 条件对照已找到的具体缺项

| 判断 | 当前通过证据 | 缺项 |
|---|---|---|
| C03 返回身份一致性 | 合法基线、owner变化、tool_call_id变化 | tool和status单独变化；owner负例还受后继guard保护，不能把宽泛异常匹配当首个guard的独立证明 |
| C08 修订对象类型/数量 | 合法修订、数量不匹配且0模型调用 | 保持数量正确，单独改变object_type |
| C18 经验发布状态 | release(v1)后可用，release(NULL)后版本不匹配被拒绝 | 可访问但从未有release行的候选；撤销版本不等于删除release行 |

这是基于真实输入、源码逻辑和断言的局部对照；没有布尔操作数运行时插桩，不能据此发布完整MC/DC百分比。完整证据与前提见Neo审核文件。

### 失败的初步归因，不把失败项数当Bug数

133个失败阶段中，113个直接报`HISTORICAL_AGENT_EXECUTION_INACTIVE`，说明这些测试仍要求已停用的历史入口执行。其余20个需分别处置，下面是已核实的代表，不冒称20个独立产品Bug，也不把未定位项一律归为过时测试。

| 代表失败 | 已找到的机制 | 处置边界 |
|---|---|---|
| generation_records的generation_record/<10000断言；object_index旧摘要字段 | 测试还要求旧裁剪/派生摘要；当前公共返回按已确认要求保留generation_notes和原始业务返回 | P2测试契约债。更新到新契约并保留原文/恢复/身份断言，不恢复裁剪来修绿 |
| generation_records调用完整主干测试缺reference_delivery | 被复用测试新增参数后，调用方未同步 | P2测试复用漂移。补覆盖两种配置，避免将某个测试函数当不稳定fixture API |
| text_work_candidate_inputs未抛大小错误 | monkeypatch改的是text_work导入别名，实际大小判断读取prepared_material模块常量 | P2失效测试探针；不能据此判定程序漏检大小限制 |
| vision期望SDK retries=0，实际为5 | 当前构造读取REPORT_SDK_RETRIES，测试未隔离该配置 | 首先是环境依赖的测试oracle，不能据此判越权重试 |
| deepseek_strict拒绝allOf（UF-STRICT） | 当前真实Coordinator schema含allOf，StrictCodec明确拒绝该结构 | Neo在本轮将原待查候选确认为P2适配兼容缺口，阻止该strict配置请求；不阻止当前非strict GLM路径。先补适配边界红例，再选最小兼容方案。原full review历史状态保留，不与Office事务的NFR-04混淆 |

clean_trial014额外状态、历史导出currentness、旧rubric检索错误等其余项保留原始证据及未定位状态，不在第0轮擅自改变产品语义。

## 已确认的覆盖缺口与下一轮变更设计

下面是Neo针对测试证据的优先级判断。测试缺口本身不等于已经确认的产品缺陷；程序缺陷需由复现和源码因果链单独确认。

| 编号 | 缺口与影响 | 下一轮涉及代码 | 边界与验证方案 |
|---|---|---|---|
| G01 / P1 | 普通CLI/Web入口是否接入累计Token预算没有入口证据。已有预算测试手动进入token_budget上下文，不能证明用户入口负责绑定。阻止宣称入口已受保护或据此开启付费，不阻止本轮离线测量。 | 先补`tests/test_token_budget.py`及CLI/Web入口测试；核查`src/report_agent/cli.py`、`webapp.py`、`deep_runtime.py`、`deep_models.py`、`token_budget.py`。 | 临时case，真实configured_model+MockTransport。正常入口登记授权、超额0 dispatch、unknown保留预占；测试不能替入口手动with budget。若没有Host授权policy接口，先明确设计缺口，不发明默认额度。应用改动由红例决定，再说明具体范围。 |
| G02 / P2 | 已有文字工具恢复证据不能覆盖Artifact审核和摘要的兄弟路径。 | 先补`tests/test_bounded_artifact_text_work.py`、`test_glm_native_summary.py`、`test_summary_context_provenance.py`；候选应用边界为`artifact_review.py`、`working_summary.py`和已有操作生命周期模块。 | 分别注入派发前拒绝、已派发结果未知、收到响应后解析/保存失败、同ID重放；断言请求次数、账本状态、原文收据及副作用。先定位共同原因，再决定是否共享修复，不逐处加补丁。 |
| G03 / P2 | 当前接口分母缺少逐接口、角色、配置和等价类的完整断言映射；调用入口记录不能代替契约验收。 | `tests/test_boundary_refactor.py`、`test_evidence_interface.py`、已有Driver/fixtures；候选应用边界`tool_transport.py`、`task_context.py`、`decision_data.py`、`prepared_material.py`、`text_work.py`。 | 以最终绑定schema为分母；检查缺料、拒绝、offload后的下一模型输入、Source到独立工具packet、receipt到原样adopt。契约/身份/限制不得失真，失败不能变成成功；正常同快照Word/XLSX链路同时保留。 |
| G04 / P2 | 三组已审判断仍缺独立条件反例，其余15组及尚未清点的关键判断未知。 | `tests/test_boundary_refactor.py`、`test_text_work_scoped_revision.py`、`test_learning.py`及对应现有测试。 | 每个反例只改变目标条件，保持其他前提，断言准确错误码和零不当副作用。不得把同一宽泛异常或多个同时变化的条件当MC/DC。按Neo条件表补缺项。 |
| G05 / P2 | 测试树中存在旧入口/旧契约与当前有效入口混用，失败原因须逐项归类；未通过测试不能计为已证明行为。 | 当前失败涉及的测试/fixture，详见逐项失败清单；不预先授权修改应用来迎合旧测试。 | 保留原始失败。区分旧接口已明确退役、当前产品回归、环境/可选依赖、尚未定位。旧资料测试应证明兼容/拒绝预期，不能仅静默删除或skip。 |
| G06 / P2 | Python指标不包含前端交互、Host所有接口、所有decision_only等权限配置、第三方框架内部和真实模型语义。 | `src/report_agent/static/learning.js`、`webapp.py`、`learning_api.py`及相应测试；实际新增位置待小范围调查。 | 前端反馈目标/证据刷新用DOM/浏览器断言；Host API按实际路由列接口。配置的权限差异单独验证；SDK边界用MockTransport。真实语义验证另立小规模方案，不与本轮百分比混用。 |

下一轮先补决定性的红例与契约矩阵，再按Neo根因审核选择最小应用修复。当前这一轮不开始这些应用修复，也不重新运行真实报告。

## 代码变更与VS Code

本轮所有新增诊断代码、文档及实际差异见同目录`changes.md`和`code-changes.diff`。`src/`、既有`tests/`与`pyproject.toml`不属于本轮改动。raw结果放在忽略目录`.analysis/round0-coverage-20261018/`，避免把大批诊断归档当成新的应用模块。既有`.outputs/`、`deliveries/`、`outputs/`不计入本轮变更。
