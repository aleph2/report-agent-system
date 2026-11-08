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

## Outstanding verification

Resolve dynamic callers and false matches before switching accessors. Check production call paths before retiring tables, particularly DelegatedTask reads. The initial inventory preceded O8. Under O8, Pyright 1.1.414 and pytest-cov 7.1.0 were installed in the native Python 3.12 environment, with coverage 7.17.2 and nodeenv 1.12.0 as dependencies. No existing Python distribution changed version. Pyright reported 0 errors and 0 warnings on src/report_agent/fake03_fact_register.py. The guarded pytest runner passed all 4 tests in tests/test_fake_attestation_register.py with 64 of 73 statements covered in that module (88%). This is a tooling check only. The full M0 coverage baseline, accessor migration, and full regression remain outstanding.
