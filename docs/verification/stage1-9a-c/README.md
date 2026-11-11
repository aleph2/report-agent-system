# Part c inventory and focused verification

Scope: owner-approved [part c](../../reviews/stage1-9a-entry.md). No paid calls.
Private raw evidence: `.private/stage1-9a-c-20261110/`; original ledgers, cases and G5 are unchanged.

- [Fields](agent-fields.tsv): nested object, union and array fields from all five role factories and exercised Writer/Reviewer variants. The same business field repeats across roles, schema variants and historical caller-ID profiles. **3,320 paths is not 3,320 distinct model inputs or new requirements.** Each entry names its declared contract, capability requirement and consuming callable. Native and historical profiles are separated.
- [Checks](checks.tsv): repository-wide static index of 3,054 explicit raise/assert sites, declared Pydantic constraints/validators and planning-gap calls. [SQL](s2-checks.tsv) covers all 12 families / 13 clauses. Expressions identify the check; source/function identifies its reader. Requirement mappings are at accepted capability-family level; this index is not a new approval of every inherited constraint or proof that all conditional checks were exercised.
- [Refusals](refusals.tsv): actual LangChain SDK errors from the controlled replay, deduplicated by case + authenticated actor + native call ID. Retry invocations remain in the private raw sample. A reason/site can overlap another reason/site for the same refused call; do not add them as independent failures.
- [Summary](inventory.json): 83 SDK invocations, 82 attributed, **16 distinct rejected calls**, one unattributed successful observation retained privately; no unfinished observations or recorder errors. Writer: 76 invocations / 13 rejected calls. Reviewer: 5 / 2. Coordinator: 1 / 1. Layout and rubric-grader schemas were enumerated, but their refusal rates are **unmeasured**, not zero.
- A site with zero observed refusals gets **0 observed** and **evaluation coverage unmeasured**. An uninvoked tool/role is unmeasured. A tool's total is never represented as a field-specific rejection count. These are deliberately exercised offline failures, not production refusal rates, judgment-quality results or token measurements.
- [B2 guards](planned-guards.json) were **planned at c acceptance**. The later b2 candidate now implements both and passes focused checks; the full b2 verification now passes; owner acceptance remains pending. C’s measured inventory and scripted refusal counts are unchanged.

## Reproduction

Opt in with `-p support.record_tool_inventory` and private `REPORT_TOOL_INVENTORY`.
The plugin uses installed LangChain callbacks and factory wrappers only in that test process. It does not alter dispatcher source, enable tracing/uploads, or execute models.
Run `catalog_sample.py` explicitly; it is not added to default collection. Then run `build_inventory.py` with the two private observation paths listed by hash in `inventory.json`. The builder self-checks reference/union/array traversal. Only schemas/field names, code checks and aggregate counts are published, never private argument values or case paths.

Focused results on c production source `2c31486`:
- Assertion/storage/recovery/import/projection/guard regression: **311 passed**, 103.82s pytest time.
- Instrumented Writer/native-identity/binding/extraction/fake04/replay sample: **96 passed**, 140.70s.
- Five-role catalog enumeration: **1 passed**, 3.01s.
- Cold-copy/exclusion controls: **54 passed**, 22.36s; some overlap the core set.
- Earlier TDD failures are retained honestly: missing native Reviewer wrapping, current receipt-link/projection assertions before fixes, and the cold-copy reproduction. One initial cold-copy attempt had a missing fixture import; it was setup failure, not reproduction. No retired test was deleted or relabeled green.
- Owner subsequently authorized one clean full run on exact `a70ab4d`: **6,179 passed / 9 unchanged skips / 0 failures**, 26m29s. All 6,188 collected nodes ran once; all nine M0 coverage floors passed, overall 90.63%. [Result](clean-full.json). All 1,265 frozen files unchanged, automatic passing-copy removal, zero retained temporary test databases. Focused counts still overlap and are not added to the full-run count.

## Retained history and limits

New judgments use their assertion ID to retrieve completed business details; the accepted M2 hash-key reader remains one explicit historical fallback. Archive v2/v3 readers remain; v4 carries direct associations. New calculations omit the auxiliary projection digest; accepted historical fields still deserialize. Consumed qualifiers, original submissions, image-delivery scope, producer binding and exact-operation recovery stay tested.

The cold-copy failure was reproduced at `prepare_probe_case -> _confirmed -> require_complete`: the approved exclusion lost its old page-return evidence. The trusted import now saves private immutable `ImportedSourceReadFacts` (source version + pages) from verified frozen inputs. Exclusion validation consumes those facts. It copies no runtime receipt, grants no Writer image delivery and makes no claim about a new task reading the page. Two successive imports succeed; a changed unobserved page still fails; source bytes remain unchanged.

Full regression is now complete; owner review/acceptance, b2 implementation/rendered artifacts and the paid Fake03 run remain pending. The paid gate includes accepted a/b/c/b2, the measured inventory and a frozen answer key, plus a separate owner-approved launch scope/cap.
