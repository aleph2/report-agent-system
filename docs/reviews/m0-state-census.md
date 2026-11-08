# M0 state access and migration census

The starting point is approved S3 revision `a1e2d4bf989cc9b2757ff72c5793fc53ffc5b27a`. The original 32-family guard and its coverage/real-route findings remain in [the earlier M0 baseline](migration-m0-baseline.md). This census starts at the SQLite `state(key,value)` boundary and traces readers as well as writers. It includes Python operator scripts. There are no direct state SQL references in the two JavaScript sources or the assertion-schema SQL file at the baseline. Content-table rows, the task dispatcher, its checkpoints and the assertion database are separate boundaries.

| Record | Contents |
| --- | --- |
| [Key catalog](m0-state-families.tsv) | 162 entries at the starting tag, including the SQL wildcard predicate `operator_%`. Every entry has a classification, rationale and migration/retention disposition. The 25 assertion and 39 mixed entries require attention to report semantics. The 85 runtime and 13 legacy entries identify operational and retained experimental consumers. Slice assignments for previously unlisted families are proposed work, not completed migrations. |
| [Site ledger](m0-state-sites.tsv) | Current file, line, function, access path, operation, key expression and possible family sets. One physical database read can appear here at both the named accessor and raw SQL layers. The counts measure source dependencies. |
| [Reviewed dynamic bindings](m0-state-bindings.tsv) | Caller/callee and provenance evidence for indirect key arguments, lookup through events and saved receipts, grouped scans and imports. `@all` denotes the public Store forwarding an arbitrary key, `@accessor` and `@helper` denote private forwarders whose callers supply the key, `@scan` denotes an unrestricted or value-filtered scan, `@schema` denotes table creation, and `@empty` denotes the deliberate empty-string lookup when an episode has no prior recovery key. |
| [Tagged observations](m0-state-baseline-observed.tsv) | Baseline attempts recorded at the actual SQLite driver boundary during the six named offline test modules below. Includes fixture setup and deliberate rollback. Reads without a parseable single literal key appear as `<scan>`. |

The archived baseline has 242 Python files in scope, 1,134 dependency sites in 137 files, 732 reads, 398 writes, three deletes and one schema operation. The site layers are 452 Store method calls, 86 Store manifest property references, 268 named accessor calls, 161 helper calls and 167 SQL sites. The baseline site TSV SHA-256 is `c0d75e184a720534fbd6b5e745cd75d0520c974c7756dfd9722316b41aeaf8d6`. The full-suite trace exposed one omitted operation direction in the original scan. The two literal parameter rows in `source_search.configure_source_search` insert both `source_search_view` and `source_search_binding`. The corrected scanner evaluates the key operand in every literal batch row and retains unresolved operands for review. The other two state executemany sites copy a filtered snapshot or delete named trial keys using a comprehension. A separate AST walk matched every literal SQL table reference to a recorded SQL site. Manual review of computed table names found fixed allowlists in acceptance checkpoint inspection, assertion archive reload, and the frozen-feedback recovery script; their lists contain other tables. The raw Store connection subclass forwards its caller's statement and arguments unchanged. The same scanner applied to the integrated M1 source removes the two fake qualitative state families. The catalog keeps their historical rows; the current site ledger gives the post-M1 sites.

## Dependencies beyond the previous 32

* A writer saving an assigned prose block reaches `ContentStore.save`, then `commission_plan._set` with the result of `section_writing.prose_selection_key`. A section assignment stores a `g6_section_prose:*` version reference. An object assignment stores a `g6_object_prose:*` version reference. The prose itself lives in the selected ContentNode. Writer issues, section writing and the assembler follow these pointers. M7 must preserve the plan/section/object binding and selected version on migration.
* `review.reconcile_review` joins native grading iterations to targets and writes conclusions into `rubric_reviews`, including the target and evaluation provenance. It separately writes the native projection `rubric_status`. `rubric_targets` binds evaluation inputs. The old review and web/operator paths and review preflight still read these records. M8 must preserve findings and target/version bindings and distinguish the native status from a release or engineering sign-off.
* `review_steps` writes drafts, checks, finding locations and finalization. `qualitative_reviewer_snapshot:*` freezes Writer rows for the Reviewer. Full-text inspection/analysis receipts can contain proposed semantic content before adoption. Treating all these rows as disposable progress would lose review evidence.
* `legacy_state.insert_probe_business_state` copies a filtered snapshot inside the destination transaction. Its family set includes reviewed method packs and the source authority explicitly appended by `probe_case`. Other readers intentionally scan every state row or reach it through a capture key in an event. The generic Store API remains open to extensions and synthetic tests.
* Three operators unpack an unfiltered table snapshot. In `audit_report.audit` the projected keys include runtime, report status/activity/error, delivery, checkpoint and trace-thread ID. In `prepare_completed_feedback_recovery.validate_baseline` the projection checks acceptance mode, knowledge enablement, checkpoint/interrupt/errors, report/rubric status, delivery and manifest; recovery subsequently compares every old/new key. In `prepare_review_trial017` the projection uses feedback, issues, report/last errors, native interrupts, manifest, delivery, rubric targets, call intent and knowledge project. The grouped review-trial accessor in `audit_review_trial017` has its exact keys in the site ledger. These downstream dictionary operations consume the snapshot already recorded at its SQL read.
* The full catalog assigns the remaining entries individually. Existing O4/O5 route retention still applies. A source-reachable site does not prove production execution or semantic quality on a real slope.

## Reproduction

Run in the native project environment from the checkout root.

```sh
archive=$(mktemp -d)
git archive a1e2d4b | tar -x -C "$archive"
python3 scripts/state_census.py --root "$archive" --sites "$archive/baseline.tsv"
sha256sum "$archive/baseline.tsv"
python3 scripts/state_census.py --sites /tmp/current-state-sites.tsv
diff -u docs/reviews/m0-state-sites.tsv /tmp/current-state-sites.tsv

# The archived product is unchanged. Only the test guard gets the opt-in observer.
cp tests/support/offline-guard/{state_trace.py,sitecustomize.py} "$archive/tests/support/offline-guard/"
trace=$(mktemp -d)
(cd "$archive" && REPORT_STATE_CENSUS_DIR="$trace" /home/dysun/.venvs/report-agent-system-native/bin/python -B tests/support/run_offline_tests.py -q tests/test_no_legacy_state.py tests/test_section_writing.py tests/test_native_rubric013.py tests/test_fake03_qualitative_steps.py tests/test_writer_issue_tools.py tests/test_review_feedback.py)
python3 scripts/state_census.py --trace-dir "$trace" --observed /tmp/tagged-state-observations.tsv
```

The six-module run passed 96 tests in 38.36 seconds with one existing middleware warning. It observed 67 distinct attempted write families and 89 read family/predicate entries. It exercised both retired M1 keys and all four previously missed families (both prose selectors, rubric reviews and rubric status). Every concrete family seen in that run had a static catalog entry; grouped/value-filtered reads also emitted the scan marker.

For the full guard, set `REPORT_STATE_CENSUS_DIR` to a new absolute directory before starting the normal offline runner or its established shards. Merge separate directories by repeating `--trace-dir`. Normal Python children that inherit the offline guard instrument SQLite too. Only attempted operation and family are saved; values and dynamic ID suffixes are dropped. The observer records attempts including rollbacks, setup writes and refused transactions. It cannot prove that a row committed, which route executed in a real commission, or observe an external writer/native process bypassing Python SQLite. Cross-check for runtime-only families and unparsed writes. Absence at runtime leaves the static dependency and its migration disposition in force.

The census guardian compares complete site signatures including family sets/operands to the reviewed ledger, requires classification of every new family, and retains exact direct storage guards for the inventoried legacy family set. A site relocation with identical semantics can keep its review. New generic forwarding modes need inspection; static discovery uses the checked-in Store/accessor/helper/SQL idioms, simple aliases, source prefixes, scoped literal expressions and the reviewed indirect binding inventory.
