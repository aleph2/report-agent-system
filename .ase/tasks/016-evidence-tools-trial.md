# Task016: scoped evidence tools and one unassisted real trial

2026-09-28. Direct chat authorization: "授权邮件" confirms the implementation
and unassisted real test requested in Task015 email messages 1a0e6c9c29d6a579
and 1a0e70204c4e055a. Results go to dongyong.sun@derobotee.com through Gmail.
This supersedes the research-only boundary for this specific work; it does not
authorize unrelated deployments, experiments, attachments or engineering sign-off.

Stage: incremental integration on the previously demonstrated end-to-end trunk.
Implement optional source-scoped search with explicit scope and pagination, and
expose existing project-bound visual observation to the native rubric grader.
Unknown search arguments must produce actionable tool feedback, not silent broad
search or whole-run termination. Preserve existing positional call compatibility.
Keep other tools, prompts, rubric, review context and orchestration unchanged.
Do not encode source-specific answers or require a semantic tool sequence.

Main implements and verifies. Anscombe independently reviews boundaries and
the final patch under alignment-reviewer guidance. Offline tests cover filtering,
pagination, historical-source behavior, corrective tool feedback, async grader
vision, unchanged sources and absence of upstream write tools. Mock tests are
protocol evidence, not model quality evidence.

Prepare .runs/task016/autonomous-report using the existing clean-input importer
from .runs/task006/highway-report. Reuse verified original files and frozen OCR
only, preserving scope and hashes. No old reports, human reference report, reviews,
issues, feedback, graph identity or checkpoints. Freeze code/rules/config evidence.
Run one serial GLM5.3/high report invocation with existing deepseek-v4.1-flash
vision available on demand. Do not edit runtime, inject hints, answer source
questions or repair drafts during execution. If it pauses, record the pause;
do not silently resume. Do not promise a completed or correct report in advance.

After termination independently inspect the actual report and native trace,
including known Task014 defect classes and new regressions. Do not feed the
post-run findings back into this test. Report elapsed time, usage, selected tools,
native feedback/revisions, unresolved issues and independent verification separately.
Email a concise summary, no engineering originals/private attachments or secrets.

Baseline P2: source-scope mismatch, grader vision gap and consequential native
review misses block claims of reliable autonomous acceptance and engineering use,
not this isolated diagnostic trial. Main owns containment and disposition.
No legacy application or writable legacy state is changed. No new runtime stages,
mandatory expert roster, grading engine or graph requirement.
