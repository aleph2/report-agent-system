# Task014 unassisted same-source experiment

## Frozen setup before launch

Project: .runs/task014/autonomous-report. Existing prepare_clean_trial009.py
copied original inputs and 1,617 frozen source blocks from task006/highway-report.
Import receipt records code/configuration hashes and immutable source hashes.
Source-index SHA256: 6c094821f9b06a323fb44f9d0b0da82df0fade051a5a660403af349a1d305a00.
Original goal SHA256: a0637c7c3e3b2d377cda50d7e29ee424f14753884996c2d12b0ffff258f5cd87.
No results, reviews, corrections, issues, graph or checkpoint copied; no new OCR.

Only production change for this experiment: general evidence/claim boundaries in
src/report_agent/rules/report-review.md. File SHA256 at launch:
cff789a67297516f4b92c46bb7cb03ece799ab17a850514340bc50130f527106.
The coordinator/role/tool code is unchanged and fingerprinted in import-receipt.
Actual assembled model messages and tool observations are locally audited by
LocalAudit; this record does not substitute a role paragraph for the effective
runtime prompt. No historical sample corrections are injected as instructions.

Native dependencies: deepagents 0.7.19, langchain 1.4.2, langgraph 1.2.12,
langchain-openai 1.6.6, openai 2.54.0. Existing GLM5.3 configuration: high
reasoning, thinking enabled, clear_thinking false, non-streaming, max_tokens
65536, SDK max_retries 2 for request failures, parallel_tool_calls false.
Native rubric max_iterations remains 3, with existing terminal feedback.
Vision capability remains deepseek-v4.1-flash if chosen by the agent; use is
not mandated. No keys or provider URL are included in this record.

Pre-run focused verification: test_native_rubric013.py 6 passed (one upstream
beta warning); test_deep_runtime.py plus test_clean_import.py 29 passed.
These are framework/protocol/isolation checks, not content-quality evidence.
Rawls independently verified the actual new project's empty outcome/checkpoint
state, equality of original source records, all 10 original file hashes, and the
1,617-block index. Three additional offline clean-import/virtual-file-boundary
tests passed; see 014-clean-inputs.md. No blocking isolation issue was found.
Main proceeds with one unassisted real invocation using the existing launcher;
no runtime continuation is silently authorized merely by this experiment record.

## Evaluation contract

No runtime developer corrections, source edits, manual report rewrites, artificial
human decisions or code/rule changes during this run. Native rubric feedback is
part of the system under evaluation. A technical recovery or human answer must
be separately labelled assistance, never hidden as uninterrupted autonomy.

Post-run independent assessment will compare the actual final draft with original
commission and relevant source observations: delivered scope, attribution and
missing-data claims, input/rule qualification and arithmetic, useful export and
unresolved human decisions. Record detected defects, feedback receipt, revisions,
residuals and false alarms separately. Do not inject this assessment into this run.
An absent historical defect does not prove the grader detected it. This known
development case is not held-out evidence or a prompt-only causal comparison.

Diagnosis and independent review: 014-review-diagnosis.md, 014-alignment.md.
The baseline P2 review-miss risk remains unproven; this is a contained diagnostic
report generation, not engineering approval or production promotion.
