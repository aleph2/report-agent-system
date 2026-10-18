# Task043 — implementation and native evidence record

2026-09-29. Main resumes after the user's explicit continuation. Stage: candidate
assessment before implementation; G1 still open. No Task043 model run or production
change has occurred at this initial record. Task042 was preserved in commits
2240e1a and ee957f6, including its failed/unscoredA and valid but unsoundB verdict.

Main chose a general source-search observation candidate with the LLM/RL specialist's
recommendation. review_fork is mapping existing interfaces and Task027 prior evidence
in 043-source-context-assessment.md; it must not modify runtime during that assignment.
Main identified reusable source-only import/native graph support in
scripts/run_selected_evidence_probe.py and will preserve its new-ID/no-history and
no-author-loop limitations. Independent alignment review of the concrete candidate
precedes implementation. Evidence and final role/file ownership will be appended.

## Pre-implementation alignment review

alignment_review accepts the generic deferred-table design under C25, with the
original matches and agent-selected full/page access preserved. It requires
explicit unexpanded/not-extracted status, accurate source/page provenance including
unlocatable records, default unchanged behavior, and independently bound format/
default configuration in both freeze and native review target identity. Main
accepts these boundaries; a direct probe must validate binding itself, not rely
only on run_report. Normal newly assigned IDs and changed fresh history remain
declared differences, not a single-factor replay of040.

P2-043-A01: run_selected_evidence_probe.prepare_candidate and
prepare_clean_trial009.prepare open the original SQLite baseline directly with
mode=ro without the protected snapshot procedure. Existing017/040 evidence shows
that this can create WAL/SHM sidecars in the original directory. The finding blocks
executing that old preparation path directly against protected040; it does not
block implementation/offline evaluation. Main will reuse the existing baseline
lock and temporary main/WAL snapshot read primitives, preserve original source/
result content, and check the baseline file set/hashes before and after. No live
service is changed and no legacy application code is imported. Main owns the
preparation fix and its focused regression evidence before any043 model call.

The previous027 compact geometry trial is relevant prior evidence: geometry size
fell locally but the native verdict remained all-pass. Its flags also require
unrelated legacy prompt/context settings and a017 checkpoint fork. Main will not
enable that chain for043. The new candidate changes when the table supplement
enters a search observation, retaining full old output on explicit request; this
also changes evidence access, so it is not a pure context-length intervention.
