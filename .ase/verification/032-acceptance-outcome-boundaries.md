# Task032 verification

In progress, 2026-09-29. Stage: critical-risk validation, G1 open. Main implemented
three scoped guidance/schema-description edits; no field/default/validation/storage
or model-parameter changes. Task031 remains immutable historical failure evidence.

## Independent reviews and offline evidence

alignment_review independently reviewed the proposal and actual three-file diff.
No blocking findings: outcome definitions preserve strategy autonomy, requirement
scope, owner permissions and genuine uncertainty. Main accepts the caveat that
new/old criteria must have equivalent requirements and combined improvements cannot
be attributed to a single factor. Three diagnostic arms and a separate generated-
standard trunk enforce these evidence distinctions. This is development review,
not a new runtime role or semantic approval.

review_fork independently authored fresh synthetic controls in ignored
`.analysis/task032/heldout_controls.json`, including expected labels stored only in
evaluator_only. Fixture SHA256:
c682a82ff1258be8aed552d0cf516e579638a5b0e7c71285cc142a0635b9727d.
Four cases, four criteria:9 satisfied,4not_satisfied,3undetermined expected across
one complete set. The fourth case adds a transparent missing-value supplement for
a genuine all-pass control. Baseline/clear condition,scope and requirement_refs are
identical. The tester checked Decimal rounding, source correspondence and labels.

Main accepted two tester harness observations: direct nested-grader invocation does
not exercise native coverage-retry/outer revision, so malformed ID coverage cannot
be scored as a semantic label; order was improved before any calls to rotate by
case then reverse the same ordering on repetition2. No paid outcomes were used to
tune fixtures or prompts. The full synthetic trunk separately uses the normal native
application and actual coordinator-generated criteria, not diagnostic criteria.

Offline:70 existing acceptance/contract/context/feedback tests passed (84.39s).
Six added diagnostic isolation tests passed (8.80s): evaluator-field rejection at
all input levels, exact source/criteria/draft adoption, actual prompt-target hash,
public-only output, scoped prompt restoration and attempted-run replay rejection.
These are deterministic evidence, not proof of model accuracy. No application
source/document data was modified. Runtime freeze and live results follow below.
