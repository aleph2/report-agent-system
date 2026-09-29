# Task040 — evidence-backed feedback in the real report recovery trunk

2026-09-29. User requested continuing paid grader improvement and email contact,
and proposed feedback with the agent recording its improvement. Main owns delivery
and execution. This follows the finite Task038/039 diagnostics and returns to the
useful-real-report trunk. G1 remains open; stored feedback is not learned behavior.

## Intended outcome

Use the application's normal coordinator/author/native-review path to handle
independently verified correction feedback on the unchanged historical report.
Determine whether feedback is received, sources are consulted, the report is
materially corrected and the new version is assessed on the original standards.
The application owns report editing and calculations; development agents provide
located observations, then audit actual results. This is informed recovery, not
blind discovery, a new acceptance standard or a claim of cross-case learning.

## Isolation and preparation plan

Use the completed Task033 boundary-guidance run as a read-only baseline. Its
selected draft ad297419-5aa2-41fb-aa6f-c80f722fe352 has the same original body
as Task034 (SHA25607c5933c882cadf8b3099785501726bdc54cd0d3a4f83272ce80e99fb64af7b7).
Task034 is only a nested grader probe, without the complete author checkpoint.
Create one independent writable completed-state copy after locking the baseline,
using existing greenfield SQLite snapshot/backup primitives. Preserve originals,
source/OCR hashes, result identities, historic verdicts and public evidence. Do not
rewind to the old pre-review node or reuse017's static-rule import procedure.
Verify the copied checkpoint is terminal without inspecting/exporting message
bodies or private reasoning. Relocate only destination-owned generated file paths
as required; list each transformation and prove baseline hashes unchanged.

Save a result-bound request_correction in the copy, with origin identified in the
description and a separate development_feedback_delivered audit event. Do not use
Store.add_feedback: that API represents operator requirement feedback, changes the
requirement basis, and currently does not expose its text in coordinator project_view.
The result-bound correction is a real observation, not a fabricated user engineering
decision or a replacement of upstream source/acceptance ownership.

Feedback identifies verified report/source contradictions for R31 rainfall and
R42 facility-location mappings, states why the old pass is not sufficient evidence,
and asks responsible agents to assess and resolve the consequential report errors
against the unchanged commission. It must not permit inventing new site facts to
retain an incorrect score, mandate tool order, silently choose an optimal R42 point
value, or force acceptance/rejection without evidence. Existing task autonomy and
upstream read-only boundaries apply; source contradictions/real missing facts go
to humans. No new engineering design or engineering sign-off.

## Execution and verification

Complete Task039 and diagnose any execution errors first. Then invoke the existing
run_deepagents_trial.py on this prepared copy with --resume and explicit recovery
authorization. Preserve the deployed role/schema/model configuration and all actual
I/O. A terminal checkpoint receives a new project-state observation; a pending node
or interruption is not assumed terminal or blindly replayed. Actual model requests,
roles, underlying continuations and token usage are recorded, not limited by a new
cumulative quota. Diagnose failures before continuation; no blind paid retries.

Inspect the first coordinator request to establish actual feedback arrival. Compare
new report versions, target mappings, repeated values, affected calculation/grade
consistency, scope/limitations and unchanged supported material. Verify replacement
lineage and that standards were not weakened. Verify final review targets the new
report/export identity and actually received evidence. correction_addressed alone
does not establish semantic correction. Record partial success and unresolved
findings honestly; do not turn a generated DOCX or model pass into G1 acceptance.

Main coordinates independent post-run testing and relevant alignment review inside
the existing ASE review step. Review P2/P3 findings by actual impact, containment
and exact blocked action; do not stop contained recovery merely to perfect local
feedback. Email material results and user questions in the existing thread.

Existing public plan/tool/output records may establish within-run adaptation.
There is no implemented general cross-project lessons mechanism in this task;
saving feedback, receiving it, revising a report, reusing an observation and passing
an unseen case require separate evidence. No hidden thought inspection, graph
copy/use, legacy writes, new service deployment or automatic email listener.
