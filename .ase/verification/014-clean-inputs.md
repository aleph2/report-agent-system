# Task014 Clean Inputs and Tool Boundary Audit

Date: 2026-09-28. Independent implementation reviewer; actual trial inspected
read-only. No model requests, credential reads, production edits, engineering
answer review, or writes to Task006/Task014. This is a pre-start observation,
not a claim that a running trial will remain empty.

## Disposition

No confirmed isolation defect blocking the authorized Task014 trial. The actual
new project contains the approved Task006 manifest inputs and frozen extraction,
not prior results, analyses, reviews, feedback, issues, graph identity or native
checkpoints. No evidence of Task013 output import was found. This is input and
tool-boundary evidence, not report-quality or model-autonomy acceptance.

## Actual Project Evidence

Baseline: `.runs/task006/highway-report`.
Destination: `.runs/task014/autonomous-report`.
Database connections used SQLite `mode=ro` and read transactions; only schema,
key names, counts, equality checks and hashes were emitted, not source text.

- Import event: sequence 1, `2026-09-28 05:33:29` (database timestamp),
  `clean_inputs_imported`; it was the only event at inspection.
- Root entries: `sources`, `state.db`, `import-receipt.json` only.
- State keys: `manifest`, `status`, `report_status`, `clean_import` only;
  both status values were `ready`.
- `artifacts`, `analyses`, `work_items`, `results`, `result_replacements`,
  `source_versions`: each had zero rows. No checkpoint file, prior issues,
  review targets, feedback, agent summary, delivery or knowledge project ID.
- 9 source records plus the scope-instruction file: all 10 copied originals
  resolved inside the respective project's `sources` directory. Every baseline
  and destination SHA256 matched its manifest value.
- Goal, complete source records and scope record equalled Task006 exactly.
  Manifest root keys were only `goal`, `sources`, `scope_instruction`, `export`.
  Source keys were extraction/provenance metadata, not results or reviews.
- All 1617 ordered `(source_id, ordinal, locator, text)` records equalled the
  baseline; computed index hash matched the receipt:
  `6c094821f9b06a323fb44f9d0b0da82df0fade051a5a660403af349a1d305a00`.
  Goal hash also matched; database receipt equalled the JSON receipt.
- All code files listed in the receipt matched at inspection. The receipt does
  not hash the rules Markdown, preparation script, dependency installation or
  effective configuration. Main records rules/config separately in
  `014-autonomous-feedback.md`; this audit does not claim receipt coverage for them.

## Import and Effective Surfaces

- `scripts/prepare_clean_trial009.py:20` requires a new non-overlapping
  destination and reads the baseline database read-only. Lines 31-53 allow only
  goal/sources/scope, check source-index membership and original hashes, copy
  bound originals, and initialize a fresh Store. Lines 55-61 import only source
  blocks and initialize a fresh Workspace. No old outcome tables or checkpoint
  files are copied. Export configuration is newly derived, not reused from Task013.
- `src/report_agent/deep_runtime.py:416` builds native DeepAgents with explicit
  role prompts and `StateBackend`; line 422 limits file tools to
  `ls/read_file/write_file/edit_file/glob/grep`. No shell, Python execution,
  arbitrary-path document import or host filesystem backend is supplied.
  General-purpose subagent is disabled; explicit roles are knowledge/writer/reviewer.
- Coordinator prompt and role instructions (`deep_runtime.py:28`, `:36`, `:59`)
  are application-level guidance, not a report/answer. Initial human context is
  `project_view(workspace)` (`:133`, `:500`), whose source is this project's state
  and source catalog (`workspace.py:598`). Native filesystem/todo/subagent/rubric
  middleware contributes its own instructions; the effective prompt is therefore
  more than the coordinator constant, but is not loaded from old trial transcripts.
- Current grader rules are read explicitly from `rules/report-review.md`
  (`review.py:56`); native grading tools are the read-only subset at
  `deep_runtime.py:431` plus bound `read_review_export` (`review.py:75`). These
  rules express general report criteria, not Task013's final report or saved
  feedback. They are intentional current program input, not an untouched historical
  harness. No claim is made that development lessons had no influence on them.
- `deep_runtime.py:450` binds checkpoints to this workspace; `:472` assigns a
  new graph project UUID when no identity exists. This review made no graph call.
- Source tools use Catalog membership and project-local blocks. Original-page
  tools use `_original` (`document_tools.py:58`): project membership, copied-path
  precedence, resolved `sources` containment or catalog blob, and SHA256 checks.
  Retained `original_path` metadata can reveal an origin path but does not grant
  file access. The model cannot turn a guessed developer path into an original.
- Installed DeepAgents 0.7.19 `backends/state.py:38`, `:80` stores/reads the
  LangGraph `files` channel, not host files. `graph.py:865`, `:908` enables
  skills/memory only when explicitly supplied; this build supplies neither.
  Repository AGENTS/developer files are not automatically loaded as agent memory.

## Minimal Offline Verification

New file only: `tests/test_clean_trial014.py`. Ran with the project's WSL venv:

```text
python -B -m pytest -q tests/test_clean_trial014.py
3 passed in 3.38s
```

One test seeds synthetic old artifacts/results/tasks/analysis/feedback/issues,
review metadata, graph identity, checkpoint and manual-report file. The actual
preparation helper copies only original inputs/blocks into a new project.
Two parametrized native-graph tests exercise coordinator and delegated writer,
with current rules enabled and scripted offline models. Their effective tool
bindings contain the six virtual file tools and no shell/execute/import tool.
Reading an existing host development sentinel returns not-found; virtual-file
write/read succeeds without creating a host file. Captured model messages contain
neither the host secret nor old outcomes. Native interrupt ends each test before
grading; these tests do not claim to exercise a completed grader/model run.
HTTPX send and socket connection entry points were disabled in the tests.

## Boundaries and Unknowns

The importer deliberately trusts the approved baseline goal, source content,
OCR blocks and scope. It copies nested source metadata verbatim, rather than
semantically sanitizing source documents. Hash equality establishes unchanged
reuse, not OCR correctness or absence of instructions inside original material.
The outline/format/scope documents already approved as inputs remain included;
"no prior report import" does not mean "no user-authored source documents".

No engineering content or answers were evaluated. Existing source text could
contain untrusted instructions; current prompts treat sources as data. Offline
tool isolation is not proof of model resistance to all prompt injection or an
OS sandbox. Authorized application code still reads its rules and project-bound
originals. No paid request payload, later operator input, future runtime state or
completed report was inspected. These limits do not establish a current blocker.
