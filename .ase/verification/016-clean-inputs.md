# Task016 Clean-input Check

Independent reviewer observation: **2026-09-28 09:23:11 UTC / 17:23:11 Asia/Shanghai**.
Disposition: **no confirmed input-isolation blocker for the authorized single run**.
This is a pre-start snapshot, not a guarantee that the workspace stays empty after launch.

Baseline: `.runs/task006/highway-report`.
New project: `.runs/task016/autonomous-report`.
Method: Task014-style SQLite `mode=ro` transactions, structural equality and file
SHA256 checks. No Store/Workspace constructors, graph requests, model calls,
credential reads, runtime changes or writes inside either trial directory.
Only this verification document was added. No engineering answers were inspected.

## Verified Inputs

- Goal, full source records and scope-instruction record are exactly equal to
  Task006. New manifest root keys: `export`, `goal`, `scope_instruction`, `sources`.
- All 1617 ordered `(source_id, ordinal, locator, text)` rows equal the baseline.
- All 9 original source files plus the scope file resolve within their respective
  project's `sources` directory. All 10 baseline and copied hashes match the
  manifest SHA256 values. No extra or missing source files.
- JSON import receipt and database `clean_import` are equal. Receipt baseline,
  goal hash and source-index hash match independently computed values.

| Item | Equal SHA256 in baseline and destination |
| --- | --- |
| Goal, UTF-8 bytes | `a0637c7c3e3b2d377cda50d7e29ee424f14753884996c2d12b0ffff258f5cd87` |
| Full sources record | `c34920ee9d7abe2208ee801fd28d49b623883169f2d3256b3604393599a1b076` |
| Full scope record | `9a4fda9f4a358e7346fb9cc72e2aa6c0b2e77c89bc78e2d2e704a2a622d62e5f` |
| Ordered text-block index | `6c094821f9b06a323fb44f9d0b0da82df0fade051a5a660403af349a1d305a00` |

Structured hashes use UTF-8 `json.dumps(value, ensure_ascii=False, sort_keys=True)`,
consistent with the importer's `encode`; the scope-record hash is not the scope
file's byte hash. Each original file was checked separately by bytes.

## Verified Empty State

- Root contains only `import-receipt.json`, `sources`, `state.db`.
- State keys are only `clean_import`, `manifest`, `report_status`, `status`.
  Both status values are `ready`.
- Zero rows in `artifacts`, `analyses`, `source_versions`, `work_items`, `results`
  and `result_replacements`. No imported report, review or analysis authority.
- No feedback/issues/review-target/delivery/agent-summary state, no
  `knowledge_project_id`, and no `checkpoints.db`. Thus no prior graph namespace
  is adopted; this check did not inspect or modify the graph service itself.
- Exactly one event: sequence 1, `clean_inputs_imported`, at
  `2026-09-28 09:20:41` UTC. No launch/resume/model events at inspection.

All production files included in the import receipt still match their recorded
hashes. Rules Markdown and effective model configuration are not covered by that
receipt; Main's launch record owns those fingerprints. Current
`prepare_clean_trial009.py` retains the source-only allowlist and new-directory
checks used in Task014.

## Limits

Hash equality proves unchanged reuse, not OCR accuracy, engineering correctness,
model quality or resistance to source prompt injection. This fast check does not
repeat the Task014 tool-surface tests or independently rerun the 593-passed /
9-skipped suite and four focused checks reported by Main. The original Task006
goal, scope and user-authored source documents remain trusted import inputs.
No additional tests, deployment or paid run were initiated by this reviewer.
