# Stage 1 M0 baseline inventory

Baseline: `53ee2d0c0fc2936c0ffc49471843ffebc93e83dd`. Main recorded this first M0 measurement from the tagged application source (Python and JavaScript).

Counts are source files containing the exact key or key prefix as text, including SQL. Modules, public fields and imports can match. Dynamic access through variables can be missed. These are candidates for accessor migration, not counts of live callers or test coverage.

| Slice | Key family | Matching source files | Files in the tagged source |
| --- | --- | ---: | --- |
| M1 | `fake03_qualitative_profile` | 3 | fake_verification.py, writer_assessment.py, writer_indicator_steps.py |
| M1 | `fake03_qualitative_actor:` | 2 | writer_assessment.py, writer_indicator_steps.py |
| M2 | `writer_indicator_steps:` | 3 | fake_indicator_retry.py, qualitative_review.py, writer_assessment.py |
| M2 | `writer_page_read:` | 1 | writer_assignments.py |
| M2 | `writer_assessment_draft:` | 1 | writer_assessment.py |
| M3 | `assessment_receipt:` | 5 | assessment_completion.py, g3_export.py, rescue_projection.py, risk_scoring.py, system_assembler.py |
| M3 | `g6_assessment:` | 6 | assessment_completion.py, rescue_projection.py, risk_scoring.py, system_assembler.py, writer_assessment.py, writer_runtime.py |
| M3 | `g6_assessment_producer:` | 1 | risk_scoring.py |
| M4 | `commission_plan` | 40 | assessment_completion.py, cli.py, commission_brief.py, commission_carryover.py, commission_owner_records.py, commission_plan.py, commission_planning.py, commission_requirements.py, commission_results.py, commission_skeleton.py, content_delivery.py, content_store.py, content_tasks.py, deep_runtime.py, delivery_guard.py, fake_indicator_retry.py, fake_verification.py, g3_export.py, hierarchical_tools.py, material_issues.py, method_pack.py, mini_commission.py, planning_budget.py, planning_guard.py, planning_inputs.py, probe_case.py, qualitative_review.py, rescue_projection.py, review_coverage.py, risk_scoring.py, section_writing.py, source_access.py, system_assembler.py, text_work.py, writer_assessment.py, writer_assignments.py, writer_indicator_steps.py, writer_issues.py, writer_probe.py, writer_runtime.py |
| M4 | `commission_confirmation` | 8 | commission_carryover.py, commission_owner_records.py, commission_plan.py, deep_runtime.py, fake_indicator_retry.py, fake_verification.py, mini_commission.py, probe_case.py |
| M4 | `commission_skeleton` | 6 | commission_carryover.py, commission_owner_records.py, commission_planning.py, commission_requirements.py, commission_skeleton.py, probe_case.py |
| M4 | `commission_planning_draft` | 4 | commission_owner_records.py, commission_planning.py, commission_skeleton.py, planning_guard.py |
| M4 | `commission_text_profiles` | 3 | commission_planning.py, commission_skeleton.py, probe_case.py |
| M5 | `commission_requirements` | 10 | commission_plan.py, commission_planning.py, commission_requirements.py, commission_skeleton.py, content_export.py, content_workbook.py, mini_commission.py, planning_budget.py, planning_guard.py, probe_case.py |
| M5 | `commission_requirements_checkpoint:` | 1 | commission_planning.py |
| M5 | `commission_source_roles` | 7 | commission_plan.py, commission_requirements.py, deep_runtime.py, mini_commission.py, probe_case.py, risk_scoring.py, section_writing.py |
| M5 | `commission_owner_records` | 10 | commission_owner_records.py, commission_plan.py, commission_planning.py, commission_requirements.py, commission_skeleton.py, content_export.py, content_workbook.py, material_issues.py, probe_case.py, system_assembler.py |
| M5 | `commission_checkpoint:` | 2 | commission_plan.py, planning_budget.py |
| M6 | `report_issues` | 11 | acceptance.py, commission_plan.py, commission_planning.py, deep_runtime.py, delivery_guard.py, planning_budget.py, planning_guard.py, repetition_guard.py, review.py, task_context.py, workspace.py |
| M6 | `g6_issue_record:` | 3 | section_writing.py, system_assembler.py, writer_issues.py |
| M6 | `g6_issue_binding:` | 3 | section_writing.py, system_assembler.py, writer_issues.py |
| M6 | `g6_issue_route:` | 1 | system_assembler.py |
| M7 | `planned_section_receipt:` | 3 | g3_export.py, rescue_projection.py, risk_scoring.py |
| M7 | `assembly_receipt:` | 1 | system_assembler.py |
| M7 | `commission_outcome:` | 2 | commission_plan.py, system_assembler.py |
| M7 | `rescue_projection:` | 1 | rescue_projection.py |
| M8 | `content_delivery` | 12 | cli.py, content_delivery.py, decision_state.py, deep_runtime.py, hierarchical_review.py, hierarchical_tools.py, knowledge_state.py, repetition_guard.py, review_status.py, static/app.js, task_context.py, webapp.py |
| M8 | `content_final_review` | 7 | cli.py, content_delivery.py, content_store.py, deep_runtime.py, hierarchical_review.py, hierarchical_tools.py, knowledge_state.py |
| M9 | `corrections` | 14 | commission_plan.py, content_store.py, deep_runtime.py, exporting.py, hierarchical_review.py, hierarchical_tools.py, learning_runtime.py, mini_commission.py, repetition_guard.py, review.py, review_context.py, static/app.js, webapp.py, workspace.py |
| M9 | `source_changes` | 5 | catalog.py, content_delivery.py, repetition_guard.py, static/app.js, workspace.py |
| M9 | `result_impact_assessments` | 1 | workspace.py |
| M9 | `decision_observation` | 3 | cli.py, deep_runtime.py, repetition_guard.py |

## Operational ownership

The tagged assessment save reads and writes `g6_assessment_producer:` in `risk_scoring.py`. It rejects an actor other than the first producer for the plan and slope. The M3 check needs two valid packets as well as the separate missing-slope refusal. `writer_page_read:` carries host delivery and identity checks. Keep these operational checks executable during migration.

## Access paths and retained routes

The baseline scan found 57 candidate files in 161 Python and JavaScript sources. The migration changed 41 existing package modules and 11 operator scripts. Each of the 32 families now has named getters and setters. Ordered prefix scans, multi-key reads, probe imports and transaction writes have separate accessors where their original SQL semantics matter. The 32-case storage test uses the real Store and a caller-owned SQLite transaction. It checks raw keys, Unicode suffixes, missing defaults, JSON null, read-your-write and rollback.

| Families from the inventory | Normal caller or conditional route | Consequence for migration |
| --- | --- | --- |
| Plan, confirmation, skeleton, draft and text profiles | `commission_skeleton.prepare_skeleton`, `commission_planning.save_item`, `commission_plan.request_checkpoint/reply` | Planning, revisions and owner confirmation depend on the current version and existing transaction. |
| Requirements, requirements checkpoint, source roles, owner records and commission checkpoint | Planning, host source-role admission, source-bound writing and owner reply | Preserve the reference that ties the approved requirements and plan to the owner decision. |
| Report issues, corrections, source changes, result impact assessments and decision observation | `Workspace` issue/revision/status, catalog import, `deep_runtime.run_report`, planning and delivery guards | Operational state reaches live dispatch, correction and status. Some call sites execute only on an exception or correction. |
| Delivery and final review | `hierarchical_tools.content_tools`, `content_delivery.current_delivery`, `deep_runtime.run_report`, CLI and web projections | Both normal delivery and older access paths consume these families. Keep the web route under O5. |
| Assessment receipt, saved G6 assessment, producer binding and planned-section receipt | `risk_scoring.save_assessment_in_transaction`, `create_planned_section_in_transaction`, `g3_export.validate_export` and assembler reads | The normal scoring/export checks share data with the retained rescue route. The binding is a runtime receipt and remains independently enforced. |
| Issue record, issue binding, issue route, assembly receipt and commission outcome | `section_writing.propose_material_issue`, `writer_issues`, `system_assembler`, `commission_plan` | The score and issue paths feed assembly and export. An outcome and its scope must survive re-open. |
| Fake03 qualitative profile and actor binding, Writer step state, page receipts and assessment drafts | Fake attestation, Writer assignment, step saves, source and image delivery, and frozen Reviewer view | The Fake03 profile is a fixture. Step progress and page/image delivery remain operational until their runtime readers move. |
| Rescue projection | `rescue_projection.project_rescue_prose` and projection verification | Retain under O4. The real-report migration does not establish that rescue state is safe to retire. |

These are source-reachable paths. The table does not assert that every conditional path executed in a real customer case. O4 and O5 stay behind accessors pending the first real report. The dispatcher still uses delegated-task storage. M10 may retire each table only after its final reader moves.

The package-wide literal guard permits the documented public payload keys, frozen dictionary lookups and two exporter module-name references in their existing scopes. The separate storage-call guard checks source and operator scripts, including grouped SQL. UI response fields, module imports and explanatory prose retain their public spelling. Static checks cover the known access idioms. New dynamically constructed keys still warrant review.

## Offline regression and coverage

Baseline `53ee2d0` had 5,811 passes and nine skips across all 5,820 collected tests after its retained retries. For the review revision `910e92a` the complete guarded release run collected 5,910 tests. 5,901 passed and 9 were skipped. All collected node IDs were accounted for once, and collection had no errors. Eight opt-in Neo4j tests require a dedicated graph endpoint. The ninth skip is the opt-in local embedding/vector integration. Tests used the repo's offline runner, native Python 3.12.14, synthetic temporary cases and privately provisioned historical regression fixtures. A checkout used for this full suite needs the established fixture bundle. The private inputs are excluded from this tag.

Baseline diagnostics and first-pass failures are retained. The initial baseline clone lacked archived fixtures, and one loaded parallel test hit its time limit. The 52 fixture-related cases passed with the archive restored. The separate integration test passed under coverage in 16.22 seconds on a quiet host with its original 30-second limit. On the accessor coverage run, the 50 ms dispatched-timeout scenario sometimes expired before mock transport entry. The test now arms the same 50 ms fault upon dispatch, with a bounded preparation phase, using the helper shared with the sibling SDK deadline regression. Both affected test modules passed together (13 tests). The authoritative full release run used the revised tests.

The full-suite line measurement below uses `pytest-cov` over `src/report_agent`, baseline and candidate. The production modules, tests and code used for coverage all come from the exact same revision. The omitted-default fix restores compatibility with callers offering only a one-argument getter. The three original presentation regression cases and the accessor tests passed. The separate operator-script measurement uses the same six referencing test files (81 tests on each revision). Entries without named test callers should be treated as residual exposure. Line coverage measures executed statements, including imports and definitions. A call's opening line without a hit warrants inspection, especially in a multiline expression. Nine historical operator scripts received zero statement hits in the 81-test operator probe.

Package-wide statement coverage went from **26,530/29,363 (90.35%)** to **26,886/29,732 (90.43%)**. The candidate denominator includes the S2 vocabulary exercised by the contract tests.

| Production module | Before | After | Accessor call lines without a recorded hit at 910e92a |
| --- | ---: | ---: | --- |
| `acceptance.py` | 139/152 (91.4%) | 140/153 (91.5%) | 102 |
| `assessment_completion.py` | 262/469 (55.9%) | 263/470 (56.0%) | all reached |
| `catalog.py` | 133/139 (95.7%) | 133/139 (95.7%) | all reached |
| `cli.py` | 102/152 (67.1%) | 103/153 (67.3%) | 140 |
| `commission_carryover.py` | 173/175 (98.9%) | 174/176 (98.9%) | all reached |
| `commission_owner_records.py` | 204/216 (94.4%) | 205/217 (94.5%) | all reached |
| `commission_plan.py` | 862/922 (93.5%) | 862/922 (93.5%) | 1010 |
| `commission_planning.py` | 710/788 (90.1%) | 711/789 (90.1%) | 79, 538, 570 |
| `commission_requirements.py` | 351/384 (91.4%) | 352/385 (91.4%) | all reached |
| `commission_skeleton.py` | 302/329 (91.8%) | 303/330 (91.8%) | all reached |
| `content_delivery.py` | 125/128 (97.7%) | 126/129 (97.7%) | all reached |
| `content_store.py` | 795/833 (95.4%) | 796/834 (95.4%) | all reached |
| `decision_state.py` | 149/152 (98.0%) | 150/153 (98.0%) | 18 |
| `deep_runtime.py` | 868/931 (93.2%) | 869/932 (93.2%) | 495 |
| `delivery_guard.py` | 94/97 (96.9%) | 95/98 (96.9%) | all reached |
| `fake_indicator_retry.py` | 0/141 (0.0%) | 0/142 (0.0%) | 38, 160 |
| `fake_verification.py` | 223/268 (83.2%) | 225/270 (83.3%) | all reached |
| `g3_export.py` | 314/343 (91.5%) | 315/344 (91.6%) | all reached |
| `hierarchical_review.py` | 118/136 (86.8%) | 119/137 (86.9%) | 192 |
| `hierarchical_tools.py` | 407/433 (94.0%) | 408/434 (94.0%) | 110 |
| `knowledge_state.py` | 70/71 (98.6%) | 71/72 (98.6%) | 61, 62 |
| `legacy_state.py` | — | 173/175 (98.9%) | — |
| `mini_commission.py` | 125/132 (94.7%) | 126/133 (94.7%) | all reached |
| `planning_budget.py` | 95/98 (96.9%) | 96/99 (97.0%) | all reached |
| `planning_guard.py` | 117/122 (95.9%) | 118/123 (95.9%) | 22 |
| `probe_case.py` | 117/132 (88.6%) | 118/133 (88.7%) | all reached |
| `qualitative_review.py` | 79/87 (90.8%) | 80/88 (90.9%) | all reached |
| `repetition_guard.py` | 115/128 (89.8%) | 116/129 (89.9%) | all reached |
| `rescue_projection.py` | 229/259 (88.4%) | 230/260 (88.5%) | all reached |
| `review.py` | 248/254 (97.6%) | 249/255 (97.6%) | all reached |
| `review_status.py` | 139/144 (96.5%) | 140/145 (96.6%) | all reached |
| `risk_scoring.py` | 418/443 (94.4%) | 416/441 (94.3%) | all reached |
| `section_writing.py` | 92/102 (90.2%) | 93/103 (90.3%) | all reached |
| `system_assembler.py` | 446/511 (87.3%) | 447/512 (87.3%) | 501 |
| `task_context.py` | 424/429 (98.8%) | 425/430 (98.8%) | 203, 206 |
| `webapp.py` | 172/198 (86.9%) | 173/199 (86.9%) | all reached |
| `workspace.py` | 432/445 (97.1%) | 432/445 (97.1%) | 409, 447, 497, 588, 626, 628, 629, 630 |
| `writer_assessment.py` | 355/368 (96.5%) | 355/368 (96.5%) | all reached |
| `writer_assignments.py` | 213/226 (94.2%) | 214/227 (94.3%) | all reached |
| `writer_indicator_steps.py` | 215/228 (94.3%) | 216/229 (94.3%) | all reached |
| `writer_issues.py` | 146/162 (90.1%) | 147/163 (90.2%) | all reached |
| `writer_runtime.py` | 138/139 (99.3%) | 139/140 (99.3%) | all reached |

| Operator script | Before | After | Accessor call lines without a recorded hit at 910e92a |
| --- | ---: | ---: | --- |
| `audit_review_trial017.py` | 0/44 (0.0%) | 0/46 (0.0%) | 28 |
| `check_layout_capabilities.py` | 0/26 (0.0%) | 0/27 (0.0%) | 13 |
| `continue_layout_live_trial.py` | 0/41 (0.0%) | 0/42 (0.0%) | 24, 42, 48 |
| `continue_reference_feedback.py` | 0/43 (0.0%) | 0/44 (0.0%) | 53 |
| `continue_report_corrections.py` | 0/52 (0.0%) | 0/53 (0.0%) | 49, 67, 75, 77 |
| `reflow_content_snapshot.py` | 0/59 (0.0%) | 0/60 (0.0%) | 31 |
| `report_host.py` | 285/310 (91.9%) | 286/311 (92.0%) | all reached |
| `run_hierarchical_live_trial.py` | 46/158 (29.1%) | 47/159 (29.6%) | 95 |
| `run_layout_live_trial.py` | 0/62 (0.0%) | 0/63 (0.0%) | 39, 56, 69 |
| `run_reference_alignment.py` | 0/75 (0.0%) | 0/76 (0.0%) | 35, 55, 56, 88 |
| `run_reference_alignment_learning.py` | 0/92 (0.0%) | 0/93 (0.0%) | 35, 55, 56, 106 |

Pyright 1.1.414 in basic mode, using the same native interpreter and package scope, reported **757 pre-existing errors at baseline and 726 on the review revision**. Comparing diagnostics by module, rule and message found zero additional diagnostics. Pyright remains an inventory of existing debt. The tools pin pytest-cov 7.1.0 and use coverage 7.17.2. No RDF dependencies were used.

The M0 guardian first identified 233 direct package storage calls on the tagged baseline. The final suite enforces 32 accessor round trips, the exact-literal policy with narrow business-field exceptions, and direct storage and SQL checks in the package and operator scripts.

### Reproduction and evidence

From the configured native environment, provision the private test fixtures through the project's existing offline fixture process, then run `python -B tests/support/run_offline_tests.py -q`. For statement data, add `--cov=report_agent --cov-report=json`. Run `pyright --pythonpath /path/to/the/native/python` against the repository config. The release was collected once and executed by complete test files in twelve offline shards, followed by the deadline-sensitive files in a serial shard. The raw reports remain on the verification host. The hashes below identify the machine evidence used here.

| Evidence | SHA-256 |
| --- | --- |
| Release per-node gate | `714cfe953ce6aed2b9d343b9e76158a50b077910a89cc920db737742d44d2a2f` |
| Baseline reconciled gate | `a49383387f5f8952ea19d5ec039188c858076a0a6c1f4a590bda6403cbd2bed2` |
| Baseline reconciled coverage | `94a438dc287f7b5cfbb8e9d4823adca183fb27f28bf2bf04b7b710ab187102a0` |
| Accessor coverage | `8a4ce075d8d9f2952678f9fb90a5b6b1f000f1b7ec676e9d161aacdd5009afc6` |
| Private fixture manifest | `6df7df08795c55dd9cd07a95e3fb005e2df199bd4ee18ce475636d7deaf2a91b` |
| Dispatch scope audit | `e77e83d4007bc99744aefa91b2fd10d1997e152f0b913b2d2b8adfa1d4a5ca1f` |
| Final Pyright diagnostics | `7a1e3a188be93ad8fff85bc70863768f9831595e73fdc596dd6896bb9c9dd6b8` |
