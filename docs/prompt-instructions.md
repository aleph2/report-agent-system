# Scoped instruction prototype

This opt-in prototype extends the existing DeepAgents `TaskContext` middleware.
It stores operator-authored instructions as immutable application data and
rebuilds their applicable view before each model call. It does not run GEPA,
change role prompts, publish learned experiences, or grant tools or ownership.

System scope means product-level applicability within the configured isolated
project store. There is no cross-project policy distribution in this prototype.
Customer/project learning libraries and canonical releases remain separate.
Existing raw feedback and learned guidance are not silently migrated or replaced.

An instruction has an ID, version, named topic, exact text, source decision,
scope, report/task targets, optional role targets, explicit override permissions
and exact overridden references. Save creates a candidate. Operator release
selects one active version of its ID; withdrawal removes it from current input.
Older versions and release events remain available. A changed scope/target needs
a new ID. Releases require the expected current version, preventing lost updates.

The scopes are system, project, report and assignment. Report instructions require
a report ID; assignment instructions also require the actual saved delegated task
ID. Runtime uses the server-bound task identity, not a model-supplied selector.
Role targets can restrict delivery to coordinator, writer, reviewer or layout.
The configured report ID is immutable; another report uses a separate project.

## Operator interface

Use `scripts/manage_prompt_instructions.py` with the existing project environment.
The project must already use `hierarchical-review-v1` and `stateful-tools-v1`.
Configuration opts that project into the prototype:

```sh
python scripts/manage_prompt_instructions.py --project /path/to/new-case configure --report-id construction-001
python scripts/manage_prompt_instructions.py --project /path/to/new-case save --file instruction.json
python scripts/manage_prompt_instructions.py --project /path/to/new-case release --id report-voice --version 1 --reason 'Explicit operator decision'
python scripts/manage_prompt_instructions.py --project /path/to/new-case preview --role writer --task-id SAVED-TASK-ID
```

`instruction.json` supplies exact approved text; do not invent a learned strategy
to populate it. The following shows metadata only; its text is a test placeholder:

```json
{
  "id": "report-voice",
  "topic": "report-voice",
  "scope": "system",
  "text": "EXACT APPROVED INSTRUCTION GOES HERE",
  "source_decision": "Reference to the direct user instruction",
  "roles": [],
  "allow_override_scopes": ["report"],
  "overrides": []
}
```

Only allow report exceptions when the approving instruction permits them. A
report instruction overriding this entry must use the same topic, provide its
report ID, and name `{"id":"report-voice","version":1}` in `overrides`.
Creating version 2 uses `save --expected-version 1`; activating it uses
`release --version 2 --expected-active 1`. Withdraw with `release` without
`--version`, supplying `--expected-active` and a reason. Management is host-only,
not available as an agent tool; saving/releasing is not a model-driven action.

## Conflict and delivery behavior

Applicable active instructions with different text under the same topic are an
unresolved conflict unless an explicit permitted override references the exact
broader version. Conflicting alternatives stay visible in `scoped_instructions`
and are excluded from its effective list. Other topics remain available. The
coordinator/operator resolves dependent work; there is no extra agent stage or
automatic later-text-wins rule. Updating the broader version invalidates an
exception tied to its old version. Reaffirm the exception explicitly if valid.

This is a declared-topic check, not a semantic contradiction detector. Different
topics, role prompts, raw feedback, learned guidance and source prose can still
conflict. Agents must surface those conflicts; the prototype cannot prove all
instructions consistent or correctly applied. All tool and ownership guards
remain server-enforced regardless of instruction text.

Full effective instruction text and alternatives survive context projection and
conversation compaction. Reopening a workspace uses current releases. Updates
committed before the next model-call boundary appear in its input; a call already
in flight retains its captured snapshot.

Each configured call saves exact assembled system blocks and the instruction
snapshot in the application store, then records `prompt_context_offered`. Handler
return records `prompt_context_response_received`; exceptions/cancellation record
`prompt_context_outcome_unknown` without retry. Offered input is not proof of
provider receipt, semantic compliance or successful output. Ordinary native
traces still account for model usage and actual actions.

Offline tests cover system inheritance, report/role/task isolation, candidates
versus release, immutable revisions, explicit overrides, conflict containment,
live refresh, restart, stale summaries, native graph integration and unknown
outcomes. These tests do not establish real-model report quality. A fresh report
and issue workbook require separate source and output validation.
