# Task014: autonomous evidence-based feedback

2026-09-28. User accepted diagnosing native review misses and testing without
development-side corrective hints. Stage: end-to-end trunk, reusing Task013
framework feedback/recovery tests; autonomous review quality remains unproven.

Outcome: observe whether the existing coordinator and native rubric review can
produce a useful source-grounded report and actionable corrections from original
commission/source evidence, without Main discovering and injecting sample answers.

First inspect actual Task013 missed-defect traces. Adjust only demonstrated,
generalizable review guidance or a proven capability defect. Do not add agents,
fixed per-claim checks, runtime approval stages or a new orchestration engine.
Main implements; Chandrasekhar diagnoses content-review traces; Rawls checks
input isolation; Anscombe independently reviews decision/autonomy boundaries.

Prepare a new project with the existing clean source/OCR importer, preserving
hashes and original scope. No human reference report, old drafts, corrections,
reviews, issues, derived graph, scratch files or checkpoints may enter the run.
Preserve original source documents even when they contain inconvenient facts.
Freeze effective prompts, code and model configuration before starting. This is
a fresh unassisted run on a known development case, NOT a held-out generalization
test or a controlled prompt-only comparison with older runtimes.

Run serial GLM5.3 with existing native tools and authorized vision if selected.
Do not change code/rules, inject feedback, answer human business questions or
manually improve report text during the run. Technical interruption is recorded
and invalidates an uninterrupted-autonomy claim; no silent rescue or budget reset.
Native outcome feedback remains allowed: it is the capability being tested.

After execution ends, independently assess scope coverage, source attribution,
arithmetic/qualification and usable deliverable; record misses and false alarms.
Do not send those post-run findings back into this test. Report actual native
iterations and feedback receipts, unresolved human decisions, elapsed time and
usage without equating a model satisfied verdict to engineering approval.

P2 baseline risk: native review previously accepted reports with material but
containable source/qualification errors. It blocks claiming reliable autonomous
acceptance, not this isolated diagnostic test or explicitly limited draft review.
Containment: no engineering sign-off or operational use, independent post-run
assessment, preserved exact-version evidence. Main owns final disposition.
