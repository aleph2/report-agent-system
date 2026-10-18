# Feedback learning — first implementation, 2026-10-04

Current responsibility update (2026-10-14): Learner decides strategy and useful
formulation; independent bounded tools synthesize original factual evidence.
Project-fact candidates adopt exact scoped analysis fields. No automatic release
or new model job is implied. See [current contracts](independent-text-tools.md).

The first increment adds an opt-in experience library, local operator API and CLI,
an independently invoked DeepAgents reflection agent, and report-agent tools for
finding and recording the use of active experience. Existing report generation
and existing project databases are unchanged until explicitly configured.

Feedback captures an exact content snapshot, a node from that snapshot, its prior
payload, the operator correction and existing evidence references. It does not
silently rewrite the report or certify that the correction is true. Report
revision remains with the existing producer/review path.

Experience versions are immutable candidates. Publication, withdrawal and rollback
are operator actions, unavailable to reflection/report agents. Project facts are
project-scoped; preferences and general-method candidates may be shared between
explicitly configured projects of the same customer. Cross-customer publication
is intentionally not provided in this increment. Raw source facts must not be
generalized by relabeling a candidate. A scope/kind change requires a separately
reviewed new candidate. The server enforces caller scope, not an LLM argument.

## Operator use

Run from the product directory with the existing Python 3.12 environment. Choose
an explicit customer identity and a library outside any single report run:

```bash
python scripts/manage_learning.py --project .runs/example configure \
  --library .learning/customer-library --customer customer-a
python scripts/manage_learning.py --project .runs/example feedback --file feedback.json
python scripts/manage_learning.py --project .runs/example status
```

`feedback.json` uses `snapshot_ref`, `target_ref`, `correction`, `evidence_refs`.
References are the existing `{type, id, version}` objects. Scope configuration
cannot be changed by this CLI once set. A customer ID is a host configuration,
not a label to copy from untrusted source material.

Reflection is explicitly launched with an authorized model supplied through
process configuration, never inferred from a historical run:

```bash
python scripts/manage_learning.py --project .runs/example reflect \
  --authorize-model-calls --max-steps 40
python scripts/manage_learning.py --project .runs/example release \
  --id EXPERIENCE_ID --version 1 --reason 'Checked customer preference'
# Omitting --version withdraws; selecting an earlier version rolls back.
```

The step limit is not a monetary budget. Configure provider spend controls and
obtain model-cost authorization before a live run. `run_optimizer(workspace,
model)` is also available to a host background worker. It holds the same project
lock as generation, records start/end/failure, and has no publish, source/report
write or host-shell tools. Its scratch files use StateBackend. It can investigate
and propose, or conclude that evidence is insufficient, without a required
semantic micro-workflow. A durable queue is inserted in the same transaction as
feedback. Identical feedback payloads are idempotent. `reflect` consumes pending
feedback once; an empty queue does not construct a model. Failed or uncertain jobs
are not automatically retried. `retry --feedback-id ID --reason TEXT` explicitly
requeues failed/interrupted work while holding the report project lock.

An optional bounded host loop can watch for new feedback:

```bash
python scripts/manage_learning.py --project .runs/example watch \
  --authorize-model-calls --max-jobs 3 --max-steps 40
```

It must be started explicitly with an authorized model. No live worker has been
started by development. The process polls only this project, stops at its job
bound, and exits on a model failure instead of blindly retrying. The host remains
responsible for actual provider spending limits; job count is not a currency cap.

The local workbench exposes `GET /api/learning`,
`POST /api/learning/feedback`, and
`POST /api/learning/experience/{id}/release`. Existing same-origin write protection
applies. No GET request starts a model. These are local operator interfaces, not
a public authenticated multi-user service. A user-facing visual panel remains
to be added.

## Evaluation and GEPA

`evaluate_strategy_pair` compares baseline/candidate using a caller-owned
evaluator and returns per-case results and regressions. It does not publish.
`optimize_with_gepa` is an optional DSPy adapter accepting the student program,
host metric, explicitly supplied reflection model, disjoint train/validation
case IDs, and a metric-call limit. No DSPy dependency is added to the report
runtime. DSPy 3.4.0 / GEPA 0.1.4 are pinned in `requirements-learning.txt` and
installed in a separate optional environment. An actual GEPA compile and holdout
evaluation passed with local DummyLMs and network connections blocked. The
synthetic baseline already scores perfectly, so this is compatibility evidence,
not evidence of successful strategy improvement or real report evaluation.
Official interface checked:
https://github.com/stanfordnlp/dspy/blob/main/dspy/teleprompt/gepa/gepa.py

Before promotion, retain independent holdout cases not used during optimization,
record strategy/model/evaluator versions, verify both improvements and regressions,
and compare actual report correction effort. Scoring-method edits are outside
optimizer permissions. A usage receipt is a declaration, not proof that the
strategy was correctly applied.

`learning_evaluation.run_experiment` saves an immutable experiment directory with
old/new instructions, dataset IDs and input digests, evaluator/model identities,
package versions, per-case holdout scores/feedback and regression IDs. It rejects
duplicate IDs or exact inputs across splits and refuses to overwrite an existing
experiment. It preserves a baseline copy even if an optimizer mutates its input.
Failures retain a record containing exception type rather than provider payload.
Results are not automatically published. Semantic overlap between different
inputs still requires case review. Metric-call limits do not bound total spending.

The reflection agent also persists job IDs, newly saved candidate references,
summary and execution status; neither completion nor candidate creation is a
quality verdict. The visual operator panel and real report feedback-to-revision
integration remain follow-up work.

## Verification limits

Tests use synthetic cases and a scripted model with the actual DeepAgents graph.
They establish persistence, scope isolation, publication/withdrawal/rollback,
version binding, local API protection and restricted tool access. They do not
establish autonomous learning quality, correct report revision, or engineering
acceptance. Whole-report real-provider evaluation and a second real report remain pending.
Development and self-review were performed by Main; no independent review is
claimed. Existing unrelated working-tree changes are preserved.
# 工作台反馈入口

配置经验库后，工作台的“反馈与经验”可以选择报告快照与反馈位置、查看该版本内容并保存反馈。页面将原文作为反馈上下文引用；用户填写的修改建议不因此成为已核实的工程事实。保存不会启动模型或改写报告。

## 2026-10-04 小范围真实验证

已获邮件授权后，在隔离合成项目用真实 deepseek-flash 验证。修正学习工具的 Ref 类型和经验类别枚举，限制优化者仅看到四个学习业务工具；无效工具调用、空结果或截断输出不再记为完成。18 项相关测试通过。标准工具模式、low 推理强度下真实生成三条候选；严格格式适配仍未通过，不应沿用成功结论。

两个新合成案例各做一次基线/候选生成对照。候选改善缺失信息的范围表述，但冲突案例将未决披露列为可关闭条件，未建立净质量提升证据。试验候选撤回，不推广至正式项目。此次下一项目检索由宿主执行，尚非真实整份报告的自主反馈应用闭环。详情见 `.analysis/learning/live-validation-2026-10-04.txt`，逐次输出及评价在 `.runs/learning-live-20261004-low/`。Main 执行和自查，无独立审查。

判断更正（v2）：上述关闭措辞不能单独证明质量失败。原测试未定义关闭语义，报告处理可以完成而事实冲突仍未决。当前结论为尚无定论；既未证明退化，也未建立整体改进证据。原始记录保留，最新评价见 `.runs/learning-live-20261004-low/pair-assessment-v2.json` 和 `.analysis/learning/live-validation-2026-10-04-v2.txt`。不自动重新发布候选，不改变历史报告状态。

后续段落试验：反馈 agent 从用户讨论形成三条候选，写作 agent 自主调用经验检索、保存文本并登记三条版本化应用记录；宿主未注入经验正文或指定经验 ID。实验在 18 步上限结束，尚未正常收尾。机制动作已有持久证据，业务正确性与整体质量未评估。见 `.runs/learning-autonomous-20261004-v2/application3-evidence.json`。候选只在隔离库临时启用，结束已撤回。

工具补充：经验检索为词面子串查询，无命中时提示短关键词或空查询浏览；`save_text_node` 以平面参数保存文本，仍走原 ContentStore 的授权、所有权、CAS 和幂等检查，不建立证据关系或自行发布。复杂内容与关系继续使用 `commit_objects`。

## Scoped coordination changes, 2026-10-12

`search_experience` retains literal text search by default. Its optional
`match_mode="identifier"` matches the actual active scoped experience ID exactly,
or an ID prefix of at least eight characters. A reference mentioned in another
strategy is not an identity match. Results expose the matched fields. A missing
active match does not prove that a historical or inaccessible candidate does not
exist. These mechanics do not repair unavailable dependencies in a learned
strategy; that issue is returned as feedback to the existing learner.

The model-facing `read_execution_trace` now returns message identities, tool
names and return status by default. The coordinator can request exact public
message text with the returned checkpoint, namespace and message IDs, or request
page bodies with `include_message_text=true`. Large results use the existing
actor-scoped recoverable observation mechanism. Original checkpoint messages
remain available. The low-level `read_trace` helper retains its full-text default
for existing offline readers. Current application-state tools remain the source
of present business status; neither overview metadata nor a requested tool call
establishes business completion. No tool sequence is imposed.

The user deferred the larger application-state recovery redesign. Checkpoint-based
continuation remains in place. Fresh-process recovery from application data alone,
complete role lifecycle reconciliation, durable request budgets and all uncertain
external-call outcomes are not established. The scoped changes have focused
offline verification; autonomous learning reuse and report/Excel improvement
require a separately designed real-data LLM experiment. No new paid execution or
experience publication is started by these changes.

候选经验可填写理由后发布或撤回；发布旧版本即回滚。最新候选支持编辑标题、内容、适用条件和验证要求，保存为新版本，不自动发布；过期编辑会被拒绝，范围和来源反馈保持不变。同客户其他项目的经验可见，但不能使用其他项目反馈创建修订。反馈可选择本项目已保存的Evidence或SourceArtifact版本，查看有限摘录并附加引用；新上传但尚未导入内容对象的资料暂不列入此选择器。浏览器验证使用隔离的合成项目，不能作为真实模型效果证明。

## GEPA execution-trace/report integration, 2026-10-12

The earlier native reflection worker did not invoke the optional DSPy/GEPA
scaffold. Compatibility tests did not establish that adoption. The new
`gepa_report_learning.ReportExperiment` uses GEPA 0.1.4's maintained
`LangChainAdapter` with the existing DeepAgents coordinator/writer/tools/export
runtime. It supplies real model-input hashes, tool calls/observations, producer
objects, actual Word and issue-XLSX bytes, source-grounded feedback and cost
receipts to reflection. Full effective inputs remain in each rollout's journal.
GEPA proposes the strategy wording; the developer does not supply the replacement.

The normal learner may choose `optimize_saved_guidance` when the host passes an
explicit authorized `experiment_runner` to `consume_pending`/`watch_feedback`.
An operator can invoke the same capability directly on a saved candidate through
`optimize_saved_candidate`, without repeating the learner job. An unconfigured
reflection job explicitly records that GEPA was not used. The capability cannot
change its host-bound cases, metric, runtime, budget, requirements or publication
authority. Existing native autonomy and report ownership are retained.

`scripts/optimize_report_guidance.py experiment --request CONFIG.json --output
FRESH_DIRECTORY --runtime-python REPORT_PYTHON --max-metric-calls 4` runs in the
optional learning environment. CONFIG specifies a saved scoped customer
preference, a copied seed library, real source bytes/text selections and disjoint
train/validation/holdout cases. Model subprocesses use the established report
environment and explicitly selected model configuration. No dependency upgrade
or new provider is required. File paths and credentials must stay local.

Only strategy text is editable; conditions and customer requirements accompany
every candidate unchanged. Each rollout receives a fresh copied library and
workspace. Selected guidance is serialized exactly and saved as an inactive
version in an isolated library. The holdout uses the same ordinary runtime
mapping; no Main-authored writer task or corrective tool sequence is injected.
There is no automatic canonical release. Exact saved outcomes are reused instead
of repeating provider calls; incomplete/unknown operations cannot be restarted.

Artifact byte/version/link checks are deterministic. The six content criteria
are source-grounded model judgments, recorded with locations, evidence and
pass/fail/unknown; they require human calibration before stronger quality claims.
Neither a high score nor GEPA selection establishes engineering acceptance.
Per-case request/time limits include runtime calls and SDK attempts; the GEPA
metric-call count excludes holdout, reflection and judge calls. All those calls
have separate receipts. Missing responses have unknown usage, not zero usage.
Actual live outcomes are recorded under `.runs/gepa-report-integration-20261012`;
offline compatibility success alone is not a live quality result.

GEPA's metric stopper is checked between proposal iterations; it can overshoot
inside an iteration. The integration therefore also uses the maintained
`MaxCandidateProposalsStopper` (one proposal by default) and
`ScoreThresholdStopper`. Reaching the host metric's ceiling stops further search;
it is not an acceptance verdict. A deliberate capability exercise can set
`exercise_reflection=true` to test one reflection despite a perfect baseline.
The first live pilot lacked these stopping conditions and requested a second
reflection on identical evidence; that paid repetition is retained as avoidable
evidence, rather than silently removed from its history. No pilot replay is needed
to test the deterministic stopping repair.

