# Task040 completed-state feedback recovery preparation

2026-09-29. Implementer and offline tester: `review_fork`. Main owns the actual
feedback, real preparation, model invocation and final audit. Independent
`alignment_review` reviewed the design before implementation and then read the
implementation, feedback and synthetic tests. It found no code/boundary issue
blocking the real preparation. Its caveat is retained below: the incomplete marker
is an operational constraint, not a guard enforced by the general launcher.

Implemented only `scripts/prepare_completed_feedback_recovery.py` and
`tests/test_completed_feedback_recovery.py`, plus this verification record.
No production changes, Task033/034 writes, Task038/039 frozen-file changes,
service credentials, paid calls or real Task040 destination preparation occurred.

## Behavior and boundaries

The explicit inputs are baseline directory, new destination directory, feedback
file, exact selected draft ID and expected UTF-8 report-body SHA256. The tool
refuses existing/nested destinations, symlink/junction paths, a live baseline
lock, source/index/path/hash mismatch, adopted graph facts, an enabled graph,
unresolved runtime state, missing completion evidence and a nonterminal native
checkpoint. It requires the requirement-derived mode and a current original
standard whose exact selected draft still has the recorded satisfied review.
That historical satisfaction is a recovery prerequisite, not endorsement of its
content; the correction deliberately makes it insufficient for current acceptance.

Preparation reuses Task017's read-only baseline lock, temporary main/WAL snapshot
and SQLite backup primitives. It **does not call Task017's preparation procedure**,
rewind a checkpoint, remove an old review, assign a grading ID or override
`checkpoint_resume`. Both databases are backed up into the new destination;
other baseline files are copied unchanged, except for destination-owned
`previews/*/summary.json` `docx.path` relocation. Each relocation verifies the
old baseline-bound path and copied DOCX hash and records its old/new value and
file hashes. The destination's runtime lock is newly created.

The copied native graph uses `NoCallModel`, with no provider construction or
service configuration. `aget_state` is used only to inspect its checkpoint ID,
`next`, interrupt count and metadata step/source. Code never accesses returned
`values`, message bodies, private reasoning or nested task state. The copied
checkpoint file hash must remain unchanged across this read. Framework loading
of its opaque state is not presented as human inspection of internal reasoning.

The only changed business-state key is `corrections`, written through the existing
`Workspace.request_correction` method. The description has an explicit development
review prefix denying operator requirement change, engineering decision or sign-off
authority. A separate `development_feedback_delivered` event records the feedback
file/description hashes, origin, baseline and exact target body. No `add_feedback`,
`decide_issue`, result rewrite, schema change or acceptance-standard rewrite occurs.

Postconditions require unchanged original results, criteria, source blocks,
work items, replacement mappings, artifacts, analyses, database schema and full
historical event prefix. The only added events are `correction_requested` and
`development_feedback_delivered`. The same historical review remains saved, while
the changed observation version projects its former satisfied status to
`needs_attention`; the actual `project_view` must contain the correction. The
original standard must still be current. The baseline's complete filename/byte
hash inventory and feedback file are rechecked before success.

The successful `feedback-recovery-receipt.json` is written last. It contains
baseline hashes, copied filenames, checkpoint identity/hash, migrated paths,
changed state keys, event boundary, preserved result/source/criteria identities,
feedback provenance and projection checks. New grading has not started yet.
Late failure intentionally leaves a partial destination with an incomplete marker;
it must not be launched or overwritten. This is a one-shot preparation tool,
not a general recovery service or a new production launch guard.

## Offline evidence

Executed under the existing WSL Python environment:

```text
python -m pytest -q tests/test_completed_feedback_recovery.py
14 passed in 17.27s
```

Main accepted this focused evidence and froze the core preparation script and
tests before preparing the real Task033 copy. Neither file was changed afterward.

Network and configured-model construction were denied. The successful synthetic
test runs the real native framework with scripted models: complete a baseline,
prepare a copy, then call ordinary `run_report`. Its first new coordinator request
contains the result-bound correction; the coordinator acting as writer creates a
replacement draft using the unchanged standard. Native review produces a fresh
grading run ID and iteration0 targeting that new saved draft. The old result and
old review remain unchanged; the correction becomes addressed, and all baseline
file hashes remain identical after preparation and the synthetic continuation.
This verifies infrastructure behavior, not autonomous judgment or real report repair.

Refusal tests cover wrong draft/hash, modified source, escaped source path,
graph dependencies, pending/resume/interrupt/error flags, altered standard/review
binding, external preview path, a genuinely pending native checkpoint despite
completed public flags, existing/nested/link destinations and a live lock.
A WAL test confirms that committed WAL content is copied and that no baseline
sidecar or file bytes are changed.

## Main's real-run preflight and interpretation

The intended baseline is `.runs/task033/boundary-guidance`, selected draft
`ad297419-5aa2-41fb-aa6f-c80f722fe352`, expected body SHA256
`07c5933c882cadf8b3099785501726bdc54cd0d3a4f83272ce80e99fb64af7b7`.
Main must review its actual successful preparation receipt before starting the
existing launcher with the new destination, `--resume`, and explicit recovery
authorization. Preparation does not load credentials or invoke that launcher.

Actual coordinator receipt, source consultation, changed report values and
dependent calculations/levels, replacement lineage, unchanged standards and
fresh review/export binding remain real-run audit obligations. The copied old
messages and verdict are retained as history. A correction being saved or addressed
does not establish semantic repair, correct feedback, general learning, native
grader reliability, or engineering approval. No general cross-project lessons
mechanism is added.
