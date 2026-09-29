# Task040 — preparation and decisions

2026-09-29. Main owns design, authorized execution and integration. review_fork
owns the isolated completed-state preparation script and focused offline tests;
alignment_review independently reviews recovery/ownership boundaries. Native
coordinator/author/grader perform business report changes. G1 remains open.

## Design and context decisions

Task038 is complete with7 valid of8 attempts, correct14 scoped labels but P2
feedback/protocol issues. Task039's original broad-criteria contrast is running.
Main will not keep expanding local matrices; the next useful outcome is whether
verified feedback helps the normal report production/review path produce a better
saved report. This is labeled recovery, not blind detection or model training.

Independent review_fork mapped existing code and public Task033 records. Main
accepts completed Task033 as the baseline because it has the original author
checkpoint and identical report body; Task034 native-probe lacks that checkpoint.
Existing017 primitives can safely copy a locked SQLite/WAL snapshot, but its
whole preparation procedure rewinds to a legacy pre-review node and is unsuitable.
The new small preparation wrapper must preserve the completed history and verify
no pending node/interrupt before using a normal new invocation.

P2-040-F01: Store.add_feedback saves operator-origin feedback and changes the
acceptance requirement basis, but Workspace.status/project_view omit the feedback
text for the coordinator. Its later presence in grader ReviewContext is not proof
the author received it. Scope is that global API path and a potential false
delivery claim. It blocks using that path to claim this development correction
reached the author; it does not block recovery through the existing result-bound
request_correction path. Main accepts the finding and contains it by that path;
no production fix is necessary to perform this scoped recovery. Main owns later
global-feedback delivery work when needed; do not silently relabel development
observations as human engineering/requirement decisions.

alignment_review's focused design review found no C25/ownership blocker. Main
accepts its guarantees: locked immutable baseline; new independent destination;
preserve results, criteria and historical verdicts; no017 rewind or artificial
checkpoint flags; relocate only copied generated paths; persist explicitly sourced
correction tied to the exact draft; let observation_version naturally invalidate
the stale pass; verify actual input and new review identity. These are preparation
guarantees, not a prescribed semantic investigation sequence or new runtime gate.

Main prepared .analysis/task040/feedback.md with two independently verified
contradictions and their report/source locators. R31 identifies the explicit
fixed100 rule; R42 identifies the interval conflict without choosing an optimal
new point value. Feedback identifies itself as development evidence, preserves
source/human authority and asks for coherent report outcomes and public evidence.
It does not claim to be the complete report-error list. No business text was edited,
no feedback has yet been inserted in a runtime project, and no040 model run started.

The current runtime includes Task034's optional selected-evidence analysis tool,
added after Task033. Task040 uses the current unchanged deployment candidate and
records its hashes; this is not a one-variable feedback-versus-no-feedback causal
comparison with Task033. It preserves current role/schema/model settings and
autonomous tool choice. The optional tool does not become mandatory merely
because a new recovery run is being evaluated.
