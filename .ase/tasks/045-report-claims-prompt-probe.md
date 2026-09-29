# Task045: report-claim status prompt probe

User authorized one test of the proposed paragraph on2026-09-29: report claims
are subjects of evaluation, not self-validating evidence. Risk-validation/G1
remains open. Reuse Task044 exact user message, six criteria, tools, DeepSeek
backend, request parameters, direct SDK and no-retry execution. Add only the
English translation of the approved paragraph to the system message, preserving
all existing text. No production prompt change or Task043 invocation.

Delta: `.ase/experiments/045-report-claims-addendum.txt`. Do not add a targeted
70/75–100 example, expected verdict, oracle, new sources, or mandatory procedure.
Report structure/disclosures can still be directly observed; do not presume all
claims false or source materials infallible. The model retains strategy choice.

Plan: freeze and independently check one-message-only delta; make one isolated
call; preserve public output/errors; validate protocol and score against the
unchanged042 oracle. O1 conditional inconsistency, O2 correct rainfall100 and O3
unknown actual height/unsupported asserted band stay separate. Consider false
rejection and repair quality, not just the overall label. No complete six-item
gold or stable causal effect inferred from a single before/after observation.

Main owns runner/results. Existing alignment reviewer checks only relevant prompt
and experiment boundaries; LLM/RL specialist judges public output. No private
reasoning, email, legacy modification, schema repair or automatic paid replay.
Outcome in `.ase/verification/045-report-claims-prompt-probe.md`.
