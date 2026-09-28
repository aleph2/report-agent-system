# Task023: user-requested DeepSeek V4.1 grader comparison

2026-09-28. In the authorized email thread, verified correspondent asked
"更换deepseek v4.1 模型？" (message1a0e84f14635b8ba, SPFpass). Direct chat already
authorized paid model calls and email communication. Main replied: compare the
grader first, preserve author/other roles and all task evidence. No new provider,
legacy service mutation or engineering sign-off. Current provider GET/models200
lists exact deepseek-v4.1-flash; this is not a guess at an alias or substitution
with V4Pro. Private correspondence and discovery receipts in .analysis/task023.

Stage: reliability risk diagnosis on the working review trunk. Task022 executable
observation increment is committed; its native and supplied-evidence broad false
acceptance are retained as baselines. Reviewer quality/real corrective loop remain
unaccepted. Main owns code, tests and calls; independent alignment_review checks
relevant model/protocol/ownership changes and postrun_review scores public outcomes.

Smallest design: add an explicit optional REPORT_GRADER_MODEL override for native
rubric_grader and the isolated grader_diagnostic only. Allow authorized GLM5.3 or
deepseek-v4.1-flash, reject unknown values rather than falling back. No override
retains existing GLM behavior. Keep other roles/vision unchanged. Expose explicit
--grader-model trial/diagnostic flags and record both role models in call receipts.
Reuse existing SDK/DeepAgents and opaque reasoning_content transport; no new agent,
tool sequence, source mapping or semantic rule. DeepSeek uses provider-documented
enable_thinking true, high effort; remove GLM-specific clear_thinking. Map output
limit to documented max_tokens for that model. Keep nonstreaming,65536output,
parallel false, unset sampling and existing transport retry/timeout settings.
Identical numeric limits/effort names are not a claim of identical reasoning compute.

Review identity containment: DeepSeek native execution requires a fresh isolated
imported pre-review fork with cleared evaluations/targets. Bind the selected model
to that trial before the already-reviewed early-return path; recovery must keep
the same model. Each new review target records grader_model. Switching an old
approved or partially evaluated project is rejected, preserving historical verdicts.
General production model-selection migration is outside this experiment. This
addresses the alignment review's provenance concern without relabeling old GLM work.

Validate safe request fields and opaque tool-turn roundtrip offline; perform a tiny
synthetic tool+structured-response smoke before real-source calls. Its mock tool
tests protocol only. Then reuse Task022 exact two provided-evidence input files,
candidate pair, broad commission, role/rubric and output schema; only backend and
necessary provider parameters differ. Stop on execution error, inspect before retry.
If protocol permits, run one isolated Task016 native pre-review continuation with
DeepSeek grader/GLMauthor, allowing real feedback/revision/re-review. Do not inject
known defects or override the verdict. Exact selected artifacts and safe public
inputs/outputs/settings/usage must be inspected; no hidden reasoning export.

Assessment: target-specific mismatch/match/silence/false allegation as021/022,
plus independent material non-target findings, correctness of fixes and any new
regressions. Corrected6 report still has other defects. Top-level needs_revision
alone is not success; spurious criticism is a failure too. Native acceptance
requires demonstrated useful review/author response in actual saved versions,
not mock tests or an isolated diagnostic. Single observations do not establish
general rates. Preserve original source/results and identify model-dependent
control differences; no automatic quality promotion or global deployment.

The generic ASE model-comparison feature/bugfix/refactor task roster targets coding
benchmarks; this is a report-grader comparison, using its relevant controls and
quality gates rather than inventing three unrelated software tasks.

Official sources opened2026-09-28:
- https://api-docs.deepseek.com/guides/thinking_mode/ (opaque tool-turn reasoning)
- https://www.alibabacloud.com/help/en/model-studio/deepseek-api (provider thinking,
  high effort and output limit). Provider reference takes precedence over community
  blog parameter descriptions; a synthetic actual call will verify acceptance.

Completion2026-09-28: implementation/protocol/offline regressions, both fixed input
cases and the one native isolated continuation are complete. All three report
evaluations returned satisfied, with no target correction or author revision.
Grader-quality acceptance remains open underP2-023-R01; the comparison itself is
recorded, not a model promotion. Main accepts the independent alignment and content
findings; details in023-deepseek-grader-comparison.md and023-postrun-content.md.
No new paid rerun or global provider/model change is queued by this task.
